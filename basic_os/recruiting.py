import json
import re
import database
import league
import media
import recap
import roster

# Recruiting from the save: our board, our commits and the national top prospects.
# The board and prospect lists are replaced on each sync; commits accumulate so a new one can start a storyline once.

STORYLINE_MIN_STARS = 3          # commits this good put the starter at their position under pressure
COMMITTED_STAGES = {"SoftCommitted", "Committed", "HardCommitted", "Signed"}
CLASS_LABELS = {"HighSchool": "HS", "JuniorCollege_Freshman": "JUCO FR", "JuniorCollege_Sophomore": "JUCO SO",
                "JuniorCollege_Junior": "JUCO JR", "JuniorCollege_Senior": "JUCO SR", "Transfer": "Transfer"}

def initialize_recruiting_tables():
    conn = database.get_db_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS recruits (
        player_id TEXT NOT NULL,
        list TEXT NOT NULL,          -- 'board' or 'top'
        data_json TEXT NOT NULL,
        PRIMARY KEY (player_id, list)
    )
    """)
    # Our board's influence after each synced week, so the page can show who's trending up
    conn.execute("""
    CREATE TABLE IF NOT EXISTS recruit_influence (
        player_id TEXT NOT NULL,
        week INTEGER NOT NULL,
        influence INTEGER,
        PRIMARY KEY (player_id, week)
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS recruit_commits (
        player_id TEXT PRIMARY KEY,
        week INTEGER,
        data_json TEXT NOT NULL,
        storyline_done INTEGER DEFAULT 0
    )
    """)
    conn.commit()
    conn.close()

def is_committed_to(prospect, team_id):
    return prospect.get('stage') in COMMITTED_STAGES and prospect['topSchools'] and prospect['topSchools'][0]['teamId'] == team_id

def sync_recruiting(recruiting, user_team_id, current_week):
    if not recruiting:
        return
    conn = database.get_db_connection()
    conn.execute("DELETE FROM recruits")
    rows = [(p['id'], 'board', json.dumps(p)) for p in recruiting['board']] + [(p['id'], 'top', json.dumps(p)) for p in recruiting['topProspects']]
    conn.executemany("INSERT OR REPLACE INTO recruits (player_id, list, data_json) VALUES (?, ?, ?)", rows)
    conn.executemany("INSERT OR REPLACE INTO recruit_influence (player_id, week, influence) VALUES (?, ?, ?)",
                     [(p['id'], current_week, p.get('influence')) for p in recruiting['board']])
    # A commit is anyone in our committed list, plus board players whose stage says they've committed to us
    commits = list(recruiting['commits']) + [p for p in recruiting['board'] if is_committed_to(p, user_team_id) or p.get('committedWeek')]
    conn.executemany("INSERT OR IGNORE INTO recruit_commits (player_id, week, data_json) VALUES (?, ?, ?)",
                     [(p['id'], current_week, json.dumps(p)) for p in commits])
    conn.commit()
    conn.close()

# ---------- Page data ----------

def prospect_view(p, teams, user_team_id, influence_history=None):
    """Display fields for one prospect: stars, ranks, hometown, top schools with logos, and our standing."""
    schools = []
    for school in p['topSchools'][:5]:
        team = teams.get(school['teamId'])
        if team:
            schools.append({**recap.team_view(team), "influence": school['influence'], "is_user": school['teamId'] == user_team_id})
    leader = schools[0] if schools else None
    ours = next((s for s in schools if s['is_user']), None)
    committed = p.get('stage') in COMMITTED_STAGES
    view = {
        "id": p['id'], "name": p['name'], "position": p['position'], "stars": p.get('stars') or 0,
        "class": CLASS_LABELS.get(p.get('recruitClass'), p.get('recruitClass') or ""),
        "hometown": re.sub(r"(?<=[a-z])(?=[A-Z])", " ", p.get('hometown') or ""), "overall": p.get('overall'),  # "NorthCarolina" -> "North Carolina"
        "size": f"{p['heightInches'] // 12}'{p['heightInches'] % 12}\" / {p['weightPounds']}" if p.get('heightInches') else "",
        "national_rank": p.get('nationalRank'), "position_rank": p.get('positionRank'), "state_rank": p.get('stateRank'),
        "portrait": media.portrait_url("player", media.player_portrait_file(p.get('assetName'), p.get('headAsset'))),
        "schools": schools, "committed_to": leader if committed else None,
        "status": "Committed" if committed else {"Top3": "Top 3", "Top5": "Top 5", "Top10": "Top 10"}.get(p.get('stage'), p.get('stage') or ""),
    }
    if 'influence' in p:
        trend = (p['influence'] or 0) - (influence_history or {}).get(p['id'], p.get('influenceLastWeek') or p['influence'] or 0)
        view.update(influence=p['influence'], trend=trend, leading=bool(ours and leader and ours['id'] == leader['id']),
                    behind=max(0, (leader['influence'] - ours['influence'])) if ours and leader else None)
    return view

def query_list(name):
    conn = database.get_db_connection()
    rows = conn.execute("SELECT data_json FROM recruits WHERE list = ?", (name,)).fetchall()
    conn.close()
    return [json.loads(r['data_json']) for r in rows]

def previous_influence():
    """{player_id: influence} from the second-latest synced week, for the trend arrows."""
    conn = database.get_db_connection()
    weeks = [r['week'] for r in conn.execute("SELECT DISTINCT week FROM recruit_influence ORDER BY week DESC LIMIT 2")]
    rows = conn.execute("SELECT player_id, influence FROM recruit_influence WHERE week = ?", (weeks[1],)).fetchall() if len(weeks) > 1 else []
    conn.close()
    return {r['player_id']: r['influence'] for r in rows}

def query_commits():
    conn = database.get_db_connection()
    rows = conn.execute("SELECT data_json FROM recruit_commits ORDER BY week").fetchall()
    conn.close()
    return [json.loads(r['data_json']) for r in rows]

def build_recruiting_page():
    us = league.query_user_team()
    if not us:
        return None
    teams = league.query_teams()
    history = previous_influence()
    board = [prospect_view(p, teams, us['team_id'], history) for p in query_list('board')]
    board.sort(key=lambda v: (-(v['stars']), v['national_rank'] or 9999))
    top = sorted((prospect_view(p, teams, us['team_id']) for p in query_list('top')), key=lambda v: v['national_rank'] or 9999)
    commits = [prospect_view(p, teams, us['team_id']) for p in query_commits()]
    stars = [c['stars'] for c in commits]
    return {
        "board": board, "top": top, "commits": commits,
        "summary": {"board": len(board), "commits": len(commits), "avg_stars": round(sum(stars) / len(stars), 1) if stars else None,
                    "leading": sum(1 for b in board if b.get('leading'))},
    }

# ---------- Storylines from commits ----------

STAR_WORDS = {5: "five-star", 4: "four-star", 3: "three-star", 2: "two-star", 1: "one-star"}

def create_commit_storylines(selected_model):
    """A good recruit committing at a position puts that position's starter under pressure. Each commit starts at most one storyline."""
    import storylines
    conn = database.get_db_connection()
    pending = conn.execute("SELECT player_id, data_json FROM recruit_commits WHERE storyline_done = 0").fetchall()
    conn.close()
    created = 0
    for row in pending:
        recruit = json.loads(row['data_json'])
        starter = None
        if (recruit.get('stars') or 0) >= STORYLINE_MIN_STARS:
            starter = next((p for p in roster.query_full_roster() if p['position'] == recruit['position'] and p['depth_slot'] == f"{recruit['position']}1"), None)
        busy = {s['player_id'] for s in storylines.query_storyline_rows("active")}
        if starter and starter['player_id'] not in busy and len(busy) < storylines.MAX_ACTIVE_STORYLINES:
            rank = f", ranked No. {recruit['nationalRank']} nationally" if recruit.get('nationalRank') else ""
            hometown = f" from {recruit['hometown']}" if recruit.get('hometown') else ""
            prose = f"{STAR_WORDS.get(recruit['stars'], '')} {roster.POSITION_NAMES.get(recruit['position'], recruit['position']).lower()} recruit {recruit['name']}{hometown}{rank} committed to the program"
            try:
                storylines.start_storyline("recruit", starter, None, selected_model,
                                           trigger_text=f"{recruit['stars']}★ {recruit['position']} {recruit['name']} committed", trigger_prose=prose)
                created += 1
            except Exception:
                continue  # try again next generation
        conn = database.get_db_connection()
        conn.execute("UPDATE recruit_commits SET storyline_done = 1 WHERE player_id = ?", (row['player_id'],))
        conn.commit()
        conn.close()
    return created

# Auto-initialize when recruiting.py gets imported
initialize_recruiting_tables()
