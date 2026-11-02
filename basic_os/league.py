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
    # Scoring summaries captured from the save's rolling pool (kept here after the save overwrites them)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS game_scoring (
        game_id INTEGER PRIMARY KEY,
        week INTEGER,
        plays_json TEXT NOT NULL,
        captured TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    # The game's All-America / All-Conference teams and other season awards (conference is None for national teams)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS league_season_awards (
        award_type TEXT NOT NULL,
        position TEXT,
        conference TEXT,
        team_id INTEGER,
        player_id TEXT,
        name TEXT,
        jersey INTEGER,
        class_year TEXT,
        overall INTEGER,
        portrait_file TEXT,
        score INTEGER
    )
    """)
    # Bowls and the playoff (teams are NULL until the game sets them)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS league_bowls (
        game_id INTEGER PRIMARY KEY,
        week INTEGER,
        week_type TEXT,
        name TEXT,
        home_id INTEGER,
        away_id INTEGER,
        played INTEGER,
        home_score INTEGER,
        away_score INTEGER,
        game_date TEXT
    )
    """)
    # Our rivalries as the save tracks them (replaced each sync; the game updates them after every rivalry game)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS league_rivalries (
        opponent_id INTEGER PRIMARY KEY,
        name TEXT,
        rival_rank INTEGER,             -- 1-3 for the team's named rivals, NULL for other rivalry games
        our_wins INTEGER,
        their_wins INTEGER,
        streak_ours INTEGER,
        streak_length INTEGER,
        last_ours INTEGER,
        last_theirs INTEGER
    )
    """)
    # Coaching carousel: a team's head coach or coordinator changed between two syncs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS coaching_changes (
        change_id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL,
        role TEXT NOT NULL,             -- hc, oc, dc
        old_name TEXT,
        new_name TEXT,
        season_year INTEGER,
        week INTEGER,
        stage TEXT,
        detected TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS league_conferences (
        name TEXT PRIMARY KEY,
        champ_game TEXT
    )
    """)
    # Portrait columns added after the first release
    for table, column, col_type in (("league_teams", "coach_portrait", "TEXT"), ("league_teams", "staff_json", "TEXT"),
                                    ("league_teams", "color2", "TEXT"), ("league_teams", "is_user", "INTEGER DEFAULT 0"),
                                    ("league_teams", "off_scheme", "TEXT"), ("league_teams", "def_scheme", "TEXT"),
                                    ("league_teams", "off_rank", "INTEGER"), ("league_teams", "def_rank", "INTEGER"),
                                    ("league_teams", "ratings_json", "TEXT"), ("league_teams", "conference", "TEXT"),
                                    ("league_players", "portrait_file", "TEXT"), ("league_players", "hometown", "TEXT"),
                                    ("league_players", "home_state", "TEXT"), ("league_players", "stars", "INTEGER")):
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

def staff_names(team):
    """{'hc': 'Jay Sawvel', ...} from a save team (staff with portraits) or a stored row (staff_json)."""
    staff = team.get('staff') if 'staff' in team else json.loads(team.get('staff_json') or "{}")
    return {role: (member or {}).get('name') for role, member in (staff or {}).items() if (member or {}).get('name')}

def staff_changes(old_teams, new_teams):
    """[(team_id, role, old name, new name)] for every HC/OC/DC slot whose coach changed."""
    changes = []
    for team in new_teams:
        before = old_teams.get(team['id'])
        if not before:
            continue
        old, new = staff_names(before), staff_names(team)
        for role in ("hc", "oc", "dc"):
            if old.get(role) != new.get(role) and (old.get(role) or new.get(role)):
                changes.append((team['id'], role, old.get(role), new.get(role)))
    return changes

def sync_league(league, current_week, phase=None):
    """Replaces the league snapshot with the save's data and records this week's AP poll."""
    conn = database.get_db_connection()
    cursor = conn.cursor()
    previous = {row['team_id']: dict(row) for row in conn.execute("SELECT team_id, staff_json FROM league_teams").fetchall()}
    cursor.executemany("INSERT INTO coaching_changes (team_id, role, old_name, new_name, season_year, week, stage) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       [(*change, (phase or {}).get('seasonYear'), current_week, (phase or {}).get('stage'))
                        for change in staff_changes(previous, league['teams'])])
    for table in ("league_teams", "league_games", "league_players", "league_player_games", "league_awards", "league_heisman",
                  "league_season_awards", "league_bowls", "league_conferences"):
        cursor.execute(f"DELETE FROM {table}")
    conferences = [c for c in league.get('conferences') or [] if c['name'] and c['teamIds']]
    conference_of = {team_id: c['name'] for c in conferences for team_id in c['teamIds']}

    cursor.executemany("""INSERT INTO league_teams (team_id, name, nickname, short_name, color, color2, is_user, coach_portrait, staff_json,
                                                    off_scheme, def_scheme, off_rank, def_rank, ratings_json, conference)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                       [(t['id'], t['name'], t['nickname'], t['short'], t['color'], t.get('color2'), int(t['id'] == league.get('userTeamId')),
                         media.coach_portrait_file(*staff_portrait(t, 'hc')), json.dumps(staff_view(t)),
                         t.get('offScheme'), t.get('defScheme'), t.get('offRank'), t.get('defRank'), json.dumps(t.get('ratings') or {}),
                         conference_of.get(t['id']))
                        for t in league['teams']])
    cursor.executemany("INSERT INTO league_conferences (name, champ_game) VALUES (?, ?)", [(c['name'], c['champGame']) for c in conferences])
    cursor.executemany("""INSERT INTO league_season_awards (award_type, position, conference, team_id, player_id, name, jersey, class_year, overall,
                                                            portrait_file, score) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                       [(a['type'], a['position'], a['conference'], a['teamId'], a['playerId'], a['name'], a['jersey'], a['classYear'],
                         a['overall'], media.player_portrait_file(a.get('assetName'), a.get('headAsset')), a['score'])
                        for a in league.get('seasonAwards') or []])
    cursor.executemany("""INSERT INTO league_bowls (game_id, week, week_type, name, home_id, away_id, played, home_score, away_score, game_date)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                       [(b['id'], b['week'], b['weekType'], b['name'], b['homeId'], b['awayId'], int(b['played']), b['homeScore'],
                         b['awayScore'], b['date']) for b in league.get('bowlGames') or []])
    cursor.executemany("""
        INSERT INTO league_games (game_id, week, week_type, home_id, away_id, played, home_score, away_score, home_quarters, away_quarters, home_yards, away_yards)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [(g['id'], g['week'], g['weekType'], g['homeId'], g['awayId'], int(g['played']), g['homeScore'], g['awayScore'],
           json.dumps(g['homeQuarters']), json.dumps(g['awayQuarters']), g['homeYards'], g['awayYards']) for g in league['games']])
    cursor.executemany("""INSERT INTO league_players (player_id, name, position, class_year, redshirt, jersey, team_id, portrait_file,
                                                      hometown, home_state, stars) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                       [(p['id'], p['name'], p['position'], p['classYear'], p['redshirt'], p['jersey'], p['teamId'],
                         media.player_portrait_file(p.get('assetName'), p.get('headAsset')), p.get('hometown'), p.get('homeState'), p.get('stars'))
                        for p in league['players']])
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

def sync_scoring(summaries):
    """Stores each scoring summary under its game (matched by the two teams; the save doesn't link them)."""
    if not summaries:
        return 0
    played = query_rows("SELECT game_id, week, home_id, away_id, home_score, away_score FROM league_games WHERE played = 1")
    rows = []
    for summary in summaries:
        candidates = [g for g in played if g['home_id'] == summary.get('homeId') and g['away_id'] == summary.get('awayId')]
        if not candidates:
            continue
        # A rematch (conference title game) is possible: pick the game whose final the summary reaches
        game = min(candidates, key=lambda g: abs(g['home_score'] - summary['homeScore']) + abs(g['away_score'] - summary['awayScore']))
        rows.append((game['game_id'], game['week'], json.dumps(summary['plays'])))
    conn = database.get_db_connection()
    conn.executemany("INSERT OR REPLACE INTO game_scoring (game_id, week, plays_json) VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()
    return len(rows)

def query_scoring_games(team_id=None):
    """Games we have a scoring summary for, newest first (optionally only one team's)."""
    sql = """SELECT s.game_id, s.week, g.home_id, g.away_id, g.home_score, g.away_score FROM game_scoring s
             JOIN league_games g ON g.game_id = s.game_id"""
    params = ()
    if team_id is not None:
        sql += " WHERE g.home_id = ? OR g.away_id = ?"
        params = (team_id, team_id)
    return query_rows(sql + " ORDER BY s.week DESC, s.game_id", params)

def query_game_scoring(game_id):
    rows = query_rows("SELECT plays_json FROM game_scoring WHERE game_id = ?", (game_id,))
    return json.loads(rows[0]['plays_json']) if rows else None

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

def query_player_games(week=None, through_week=None, player_ids=None):
    """Stat lines, optionally only some players' (the whole season is tens of thousands of rows; ask for less when you can)."""
    sql, params = "SELECT * FROM league_player_games WHERE 1 = 1", []
    if player_ids is not None:
        player_ids = list(player_ids)
        sql += f" AND player_id IN ({','.join('?' * len(player_ids))})" if player_ids else " AND 0"
        params.extend(player_ids)
    if week is not None:
        sql += " AND week = ?"; params.append(week)
    if through_week is not None:
        sql += " AND week <= ?"; params.append(through_week)
    rows = query_rows(sql, params)
    for r in rows:
        r['stats'] = json.loads(r.pop('stats_json'))
    return rows

def query_season_awards():
    return query_rows("SELECT * FROM league_season_awards")

def query_bowls():
    return query_rows("SELECT * FROM league_bowls ORDER BY week, game_date, game_id")

def sync_rivalries(rivalries):
    if rivalries is None:
        return
    conn = database.get_db_connection()
    conn.execute("DELETE FROM league_rivalries")
    conn.executemany("""INSERT OR REPLACE INTO league_rivalries (opponent_id, name, rival_rank, our_wins, their_wins, streak_ours, streak_length,
                                                                last_ours, last_theirs) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                     [(r['opponentId'], r.get('name') or None, r.get('rank'), r.get('ourWins'), r.get('theirWins'),
                       None if r.get('streakOurs') is None else int(r['streakOurs']), r.get('streakLength'), r.get('lastOurs'), r.get('lastTheirs'))
                      for r in rivalries])
    conn.commit()
    conn.close()

def query_rivalries():
    return query_rows("SELECT * FROM league_rivalries")

def query_coaching_changes():
    return query_rows("SELECT * FROM coaching_changes ORDER BY change_id DESC")

def query_conferences():
    return query_rows("SELECT * FROM league_conferences ORDER BY name")

def query_awards(week):
    return query_rows("SELECT * FROM league_awards WHERE week = ?", (week,))

def query_heisman():
    return query_rows("SELECT * FROM league_heisman ORDER BY rank")

def query_poll(poll_week):
    """{team_id: AP rank} for the poll released after poll_week, or {} if it was never captured."""
    return {r['team_id']: r['media_rank'] for r in query_rows("SELECT team_id, media_rank FROM league_polls WHERE poll_week = ?", (poll_week,))}

# Auto-initialize when league.py gets imported
initialize_league_tables()
