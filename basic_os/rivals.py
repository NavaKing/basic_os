import json
import database
import league
import recap
import team
import team_page
from request_cache import per_request

# Rival watch: our rivals as the save tracks them (series, streak, last meeting) next to their season so far,
# plus rivalry week: when the next game is against a rival, the hub generator and a rivalry-week issue lean into it.

TOP_PLAYERS = 3

def initialize_rival_tables():
    conn = database.get_db_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS rivalry_columns (
        column_id INTEGER PRIMARY KEY AUTOINCREMENT,
        opponent_id INTEGER NOT NULL,
        week INTEGER,
        title TEXT,
        body TEXT NOT NULL,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()

# ---------- Text pieces (shared by the panel and the prompts) ----------

def series_text(r, us, them):
    if r['our_wins'] is None:
        return None
    if r['our_wins'] == r['their_wins']:
        return f"Series tied {r['our_wins']}-{r['their_wins']}"
    leader = us if r['our_wins'] > r['their_wins'] else them
    return f"{leader} leads the series {max(r['our_wins'], r['their_wins'])}-{min(r['our_wins'], r['their_wins'])}"

def streak_text(r, us, them):
    if not r['streak_length']:
        return None
    holder = us if r['streak_ours'] else them
    return f"{holder} has won {r['streak_length']} straight" if r['streak_length'] > 1 else f"{holder} won the last meeting"

def last_text(r, us, them):
    if r['last_ours'] is None or r['last_theirs'] is None:
        return None
    return f"Last meeting: {us} {r['last_ours']}, {them} {r['last_theirs']}"

# ---------- The panel ----------

def our_meetings():
    """{opponent team id: our schedule row} for this season's games."""
    meetings = {}
    for game in database.query_full_schedule():
        opponent = team.opponent(game['opponent_name'])
        if opponent:
            meetings.setdefault(opponent['id'], game)
    return meetings

def their_season(team_id, teams, ranks):
    games = league.query_team_games(team_id)
    played = [g for g in games if g['played']]
    wins = sum(1 for g in played if recap.side_result(g, team_id)[0] == 'W')
    last = next(iter(reversed(played)), None)
    upcoming = next((g for g in games if not g['played']), None)
    view = {"record": f"{wins}-{len(played) - wins}", "rank": ranks.get(team_id) if (ranks.get(team_id) or 99) <= recap.TOP_25 else None,
            "last": None, "next": None}
    if last:
        outcome, mine, theirs, venue, opponent_id = recap.side_result(last, team_id)
        view['last'] = {"week": last['week'], "outcome": outcome, "score": f"{mine}-{theirs}", "venue": venue,
                        "opponent": recap.team_view(teams[opponent_id]) if opponent_id in teams else None}
    if upcoming:
        opponent_id = upcoming['away_id'] if upcoming['home_id'] == team_id else upcoming['home_id']
        view['next'] = {"week": upcoming['week'], "venue": "vs" if upcoming['home_id'] == team_id else "@",
                        "opponent": recap.team_view(teams[opponent_id]) if opponent_id in teams else None}
    return view

@per_request
def build_rival_watch():
    us = team.user_team()
    teams = league.query_teams()
    week = recap.default_week()
    ranks = league.query_poll(week) if week is not None else {}
    meetings = our_meetings()
    active = database.query_active_week()
    out = []
    for r in league.query_rivalries():
        row = teams.get(r['opponent_id'])
        if not row:
            continue
        them = row['name']
        game = meetings.get(r['opponent_id'])
        meeting = None
        if game:
            result = None
            if game['is_played'] and game['wyo_score'] is not None:
                mine, theirs = game['wyo_score'], game['opp_score']
                result = {"outcome": "W" if mine > theirs else ("L" if mine < theirs else "T"), "score": f"{mine}-{theirs}"}
            meeting = {"week": game['week_id'], "venue": {"Home": "vs", "Away": "at"}.get(game.get('site'), "vs"),
                       "date": game.get('game_date'), "result": result, "next": bool(active and active['week_id'] == game['week_id'] and not game['is_played'])}
        out.append({"team": recap.team_view(row, ranks.get(r['opponent_id'])), "rival_rank": r['rival_rank'],
                    "name": r['name'] or f"{them} Rivalry", "named": bool(r['name']), "series": series_text(r, us['name'], them), "streak": streak_text(r, us['name'], them),
                    "last": last_text(r, us['name'], them), "season": their_season(r['opponent_id'], teams, ranks), "meeting": meeting})
    out.sort(key=lambda x: (x['rival_rank'] is None, x['rival_rank'] or 0, (x['meeting'] or {}).get('week', 99)))
    return out

# ---------- Rivalry week ----------

def rivalry_week():
    """The rival entry when our next game is a rivalry game, else None."""
    return next((r for r in build_rival_watch() if r['meeting'] and r['meeting']['next']), None)

def rivalry_facts(entry):
    us = team.user_team()
    them = entry['team']['name']
    parts = [f"{entry['name']}: {us['name']} against {them}." if entry['named'] else f"{them} is one of {us['name']}'s rivals."]
    parts += [text + "." for text in (entry['series'], entry['streak'], entry['last']) if text]
    teams = league.query_teams()
    week = recap.default_week()
    ranks = league.query_poll(week) if week is not None else {}
    for name, season in ((us['name'], their_season(us['id'], teams, ranks)), (them, entry['season'])):
        parts.append(f"{name} is {season['record']} this season" + (f" and ranked No. {season['rank']}" if season['rank'] else "") + ".")
    return " ".join(parts)

def prompt_context():
    """Rivalry-week lines for the hub generator's dispatch and posts, or '' in a normal week."""
    entry = rivalry_week()
    if not entry:
        return ""
    return (f" THIS IS RIVALRY WEEK. {rivalry_facts(entry)} Let the rivalry color the writing: the history, the bragging rights, "
            "the fans' trash talk aimed at the other side. Use only these rivalry facts; never invent past games or scores.")

def players_to_watch(team_id):
    """'QB Liam Szarka: 253 passing yards, 2 passing touchdowns, ...' (headline numbers in words: full stat lines get garbled)."""
    import awards
    return [f"{p['position']} {p['name']}: " + ", ".join(f"{b['value']} {awards.STAT_WORDS.get(b['label'], b['label'])}" for b in p['boxes'])
            for p in team_page.top_players(team_id)[:TOP_PLAYERS] if p.get('boxes')]

def query_column(opponent_id):
    rows = league.query_rows("SELECT * FROM rivalry_columns WHERE opponent_id = ? ORDER BY column_id DESC LIMIT 1", (opponent_id,))
    if not rows:
        return None
    return {"week": rows[0]['week'], "title": rows[0]['title'], "paragraphs": [p.strip() for p in rows[0]['body'].split("\n\n") if p.strip()]}

def next_rival_game():
    """The soonest unplayed meeting with a rival (the rivalry-week issue can be written ahead of time)."""
    upcoming = [r for r in build_rival_watch() if r['meeting'] and not r['meeting']['result']]
    return min(upcoming, key=lambda r: r['meeting']['week']) if upcoming else None

def generate_issue(selected_model):
    import ai_engine, awards
    entry = next_rival_game()
    if not entry:
        raise ValueError("No rival is left on this season's schedule.")
    us = team.user_team()
    meeting = entry['meeting']
    ours, theirs = players_to_watch(us['id']), players_to_watch(entry['team']['id'])
    active = database.query_active_week()
    when = "this week" if meeting['next'] else f"in Week {meeting['week']} (it is Week {active['week_id']} now, so the game is still ahead)" if active else f"in Week {meeting['week']}"
    facts = (f"{rivalry_facts(entry)} The game is {when}: {us['name']} {'plays at' if meeting['venue'] == 'at' else 'hosts'} {entry['team']['name']}. "
             + (f"{us['name']} players to watch: {'; '.join(ours)}. " if ours else "")
             + (f"{entry['team']['name']} players to watch: {'; '.join(theirs)}." if theirs else ""))
    prompt = (f"You are a columnist for a {us['name']} fan magazine writing the rivalry week issue. Build up the game: the history and "
              f"what it means, where both teams stand this year, and the players who could decide it. Use only these facts and never invent past "
              f"games, scores or quotes: {facts} Write {awards.COLUMN_PARAGRAPHS} paragraphs separated by blank lines. "
              'Respond with ONLY JSON: {"title": "headline under 10 words", "body": "the column"}')
    for _attempt in range(3):
        try:
            data = json.loads(ai_engine.call_ollama(selected_model, prompt, force_json=True))
            body = awards.paragraphs(ai_engine.clean_text(str(data.get('body') or "")))
            if len(body) > 200:
                break
        except Exception:
            continue
    else:
        raise RuntimeError("The model didn't return a usable column. Is Ollama running?")
    conn = database.get_db_connection()
    conn.execute("INSERT INTO rivalry_columns (opponent_id, week, title, body) VALUES (?, ?, ?, ?)",
                 (entry['team']['id'], meeting['week'], ai_engine.clean_text(str(data.get('title') or "")) or entry['name'], body))
    conn.commit()
    conn.close()
    return query_column(entry['team']['id'])

def build_page():
    watch = build_rival_watch()
    upcoming = next_rival_game()
    return {"rivals": watch, "upcoming": upcoming, "rivalry_week": bool(upcoming and upcoming['meeting']['next']),
            "column": query_column(upcoming['team']['id']) if upcoming else None}

initialize_rival_tables()
