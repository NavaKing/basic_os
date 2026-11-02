import json
import database
import media

# League-wide data from the save (every team, game and player stat line) for the weekly recap.
# Everything except the poll history is replaced on each sync; poll snapshots accumulate week by week.

def initialize_league_tables():
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS league_teams (
        team_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        nickname TEXT,
        short_name TEXT,
        color TEXT
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS league_games (
        game_id INTEGER PRIMARY KEY,
        week INTEGER NOT NULL,
        week_type TEXT,
        home_id INTEGER NOT NULL,
        away_id INTEGER NOT NULL,
        played INTEGER NOT NULL,
        home_score INTEGER,
        away_score INTEGER,
        home_quarters TEXT, -- JSON list of 4 quarter scores
        away_quarters TEXT,
        home_yards INTEGER,
        away_yards INTEGER
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS league_players (
        player_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        position TEXT,
        class_year TEXT,
        redshirt TEXT,
        jersey INTEGER,
        team_id INTEGER
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS league_player_games (
        player_id TEXT NOT NULL,
        game_id INTEGER NOT NULL,
        week INTEGER NOT NULL,
        stats_json TEXT NOT NULL,
        PRIMARY KEY (player_id, game_id)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_league_player_games_week ON league_player_games(week)")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS league_awards (
        award_type TEXT NOT NULL,
        week INTEGER NOT NULL,
        player_id TEXT,
        team_id INTEGER
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS league_heisman (
        rank INTEGER,
        last_rank INTEGER,
        player_id TEXT,
        team_id INTEGER
    )
    """)
    # AP poll as it stood after each week (poll_week 1 = the poll released after Week 1's games)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS league_polls (
        poll_week INTEGER NOT NULL,
        team_id INTEGER NOT NULL,
        media_rank INTEGER,
        PRIMARY KEY (poll_week, team_id)
    )
    """)
    # Full rosters with ratings for us and our opponents (Coaches tab game plan); replaced on each sync
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS plan_rosters (
        team_id INTEGER PRIMARY KEY,
        roster_json TEXT NOT NULL
    )
    """)
    # Portrait columns added after the first release
    for table, column, col_type in (("league_teams", "coach_portrait", "TEXT"), ("league_teams", "staff_json", "TEXT"),
                                    ("league_teams", "color2", "TEXT"), ("league_teams", "is_user", "INTEGER DEFAULT 0"),
                                    ("league_teams", "off_scheme", "TEXT"), ("league_teams", "def_scheme", "TEXT"),
                                    ("league_teams", "off_rank", "INTEGER"), ("league_teams", "def_rank", "INTEGER"),
                                    ("league_teams", "ratings_json", "TEXT"),
                                    ("league_players", "portrait_file", "TEXT")):
        if column not in [c[1] for c in cursor.execute(f"PRAGMA table_info({table})").fetchall()]:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
    conn.commit()
    conn.close()

def staff_portrait(team, role):
    member = (team.get('staff') or {}).get(role) or {}
    return member.get('portraitId'), member.get('portraitAsset')

def staff_view(team):
    """{'hc': {'name': ..., 'portrait': file}, 'oc': ..., 'dc': ...} for the head coach and coordinators."""
    return {role: {"name": member['name'], "portrait": media.coach_portrait_file(member.get('portraitId'), member.get('portraitAsset'))}
            for role, member in (team.get('staff') or {}).items() if member}

def sync_league(league, current_week):
    """Replaces the league snapshot with the save's data and records this week's AP poll."""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    for table in ("league_teams", "league_games", "league_players", "league_player_games", "league_awards", "league_heisman"):
        cursor.execute(f"DELETE FROM {table}")

    cursor.executemany("""INSERT INTO league_teams (team_id, name, nickname, short_name, color, color2, is_user, coach_portrait, staff_json,
                                                    off_scheme, def_scheme, off_rank, def_rank, ratings_json)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                       [(t['id'], t['name'], t['nickname'], t['short'], t['color'], t.get('color2'), int(t['id'] == league.get('userTeamId')),
                         media.coach_portrait_file(*staff_portrait(t, 'hc')), json.dumps(staff_view(t)),
                         t.get('offScheme'), t.get('defScheme'), t.get('offRank'), t.get('defRank'), json.dumps(t.get('ratings') or {}))
                        for t in league['teams']])
    cursor.executemany("""
        INSERT INTO league_games (game_id, week, week_type, home_id, away_id, played, home_score, away_score, home_quarters, away_quarters, home_yards, away_yards)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [(g['id'], g['week'], g['weekType'], g['homeId'], g['awayId'], int(g['played']), g['homeScore'], g['awayScore'],
           json.dumps(g['homeQuarters']), json.dumps(g['awayQuarters']), g['homeYards'], g['awayYards']) for g in league['games']])
    cursor.executemany("INSERT INTO league_players (player_id, name, position, class_year, redshirt, jersey, team_id, portrait_file) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       [(p['id'], p['name'], p['position'], p['classYear'], p['redshirt'], p['jersey'], p['teamId'],
                         media.player_portrait_file(p.get('assetName'), p.get('headAsset'))) for p in league['players']])
    cursor.executemany("INSERT OR REPLACE INTO league_player_games (player_id, game_id, week, stats_json) VALUES (?, ?, ?, ?)",
                       [(p['id'], g['gameId'], g['week'], json.dumps(g['stats'])) for p in league['players'] for g in p['games']])
    cursor.executemany("INSERT INTO league_awards (award_type, week, player_id, team_id) VALUES (?, ?, ?, ?)",
                       [(a['type'], a['week'], a['playerId'], a['teamId']) for a in league['weeklyAwards']])
    cursor.executemany("INSERT INTO league_heisman (rank, last_rank, player_id, team_id) VALUES (?, ?, ?, ?)",
                       [(h['rank'], h['lastRank'], h['playerId'], h['teamId']) for h in league['heisman']])

    # The save holds the current poll (after last week's games) and the one before it.
    # Keep the current one up to date, and only fill in the previous one if we never captured it.
    if current_week and current_week >= 1:
        cursor.executemany("INSERT OR REPLACE INTO league_polls (poll_week, team_id, media_rank) VALUES (?, ?, ?)",
                           [(current_week - 1, t['id'], t['mediaRank']) for t in league['teams']])
    if current_week and current_week >= 2:
        cursor.executemany("INSERT OR IGNORE INTO league_polls (poll_week, team_id, media_rank) VALUES (?, ?, ?)",
                           [(current_week - 2, t['id'], t['mediaLastRank']) for t in league['teams']])
    conn.commit()
    conn.close()

def query_rows(sql, params=()):
    conn = database.get_db_connection()
    rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
    conn.close()
    return rows

def query_teams():
    return {t['team_id']: t for t in query_rows("SELECT * FROM league_teams")}

def query_games(through_week=None, week=None):
    """Played regular-season and postseason games, optionally for one week or up to a week."""
    sql, params = "SELECT * FROM league_games WHERE played = 1", []
    if week is not None:
        sql += " AND week = ?"; params.append(week)
    if through_week is not None:
        sql += " AND week <= ?"; params.append(through_week)
    games = query_rows(sql + " ORDER BY week, game_id", params)
    for g in games:
        g['home_quarters'] = json.loads(g['home_quarters'] or "null")
        g['away_quarters'] = json.loads(g['away_quarters'] or "null")
    return games

def query_played_weeks():
    """[(week, game count)] for every week with finished games."""
    return [(r['week'], r['games']) for r in query_rows("SELECT week, COUNT(*) AS games FROM league_games WHERE played = 1 GROUP BY week ORDER BY week")]

def query_unplayed_weeks():
    """Weeks that still have games left to play."""
    return {r['week'] for r in query_rows("SELECT DISTINCT week FROM league_games WHERE played = 0")}

def query_user_team():
    rows = query_rows("SELECT * FROM league_teams WHERE is_user = 1")
    if not rows:
        return None
    team = rows[0]
    team['staff'] = json.loads(team.get('staff_json') or "{}")
    return team

def query_team(team_id):
    rows = query_rows("SELECT * FROM league_teams WHERE team_id = ?", (team_id,))
    if not rows:
        return None
    team = rows[0]
    team['staff'] = json.loads(team.get('staff_json') or "{}")
    return team

def query_team_games(team_id):
    """Every game on one team's schedule this season, played or not, in week order."""
    return query_rows("SELECT * FROM league_games WHERE home_id = ? OR away_id = ? ORDER BY week, game_id", (team_id, team_id))

def query_team_polls(team_id):
    """[(poll_week, AP rank or None)] for every poll we've captured."""
    return [(r['poll_week'], r['media_rank']) for r in query_rows("SELECT poll_week, media_rank FROM league_polls WHERE team_id = ? ORDER BY poll_week", (team_id,))]

def query_team_player_games(team_id):
    return [dict(r, stats=json.loads(r.pop('stats_json'))) for r in query_rows(
        "SELECT g.* FROM league_player_games g JOIN league_players p ON p.player_id = g.player_id WHERE p.team_id = ?", (team_id,))]

def sync_plan_rosters(rosters):
    conn = database.get_db_connection()
    conn.execute("DELETE FROM plan_rosters")
    conn.executemany("INSERT INTO plan_rosters (team_id, roster_json) VALUES (?, ?)",
                     [(r['teamId'], json.dumps({"players": r['players'], "depthChart": r['depthChart']})) for r in rosters or []])
    conn.commit()
    conn.close()

def query_plan_roster(team_id):
    rows = query_rows("SELECT roster_json FROM plan_rosters WHERE team_id = ?", (team_id,))
    return json.loads(rows[0]['roster_json']) if rows else None

def query_team_by_name(name):
    # The schedule stores "Colorado State Rams" (school + nickname); the league table stores the two separately
    rows = query_rows("SELECT * FROM league_teams WHERE name = ? OR name || ' ' || nickname = ?", (name, name))
    if not rows:
        return None
    team = rows[0]
    team['staff'] = json.loads(team.get('staff_json') or "{}")
    return team

def query_players():
    return {p['player_id']: p for p in query_rows("SELECT * FROM league_players")}

def query_player_games(week=None, through_week=None):
    sql, params = "SELECT * FROM league_player_games WHERE 1 = 1", []
    if week is not None:
        sql += " AND week = ?"; params.append(week)
    if through_week is not None:
        sql += " AND week <= ?"; params.append(through_week)
    rows = query_rows(sql, params)
    for r in rows:
        r['stats'] = json.loads(r.pop('stats_json'))
    return rows

def query_awards(week):
    return query_rows("SELECT * FROM league_awards WHERE week = ?", (week,))

def query_heisman():
    return query_rows("SELECT * FROM league_heisman ORDER BY rank")

def query_poll(poll_week):
    """{team_id: AP rank} for the poll released after poll_week, or {} if it was never captured."""
    return {r['team_id']: r['media_rank'] for r in query_rows("SELECT team_id, media_rank FROM league_polls WHERE poll_week = ?", (poll_week,))}

# Auto-initialize when league.py gets imported
initialize_league_tables()
