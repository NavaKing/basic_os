import json
import re
import sqlite3
import os
import media

DB_FILE = os.environ.get("BASIC_OS_DB") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "dynasty_data.db")

# Depth chart slots for the starter roster, plus backups so position battles are possible
DEFAULT_DEPTH_SLOTS = {
    "Broderick Donahue": "WR1",
    "Kaleb Vance": "QB1",
    "Tyler Cross": "RB1",
    "Marcus Miller": "OT1",
    "Jalen Brooks": "DE1"
}
BACKUP_PLAYERS = [
    ("Dawson Reyes", "QB", 7, "Healthy", "None", "N/A", "QB2"),
    ("Trey Whitaker", "WR", 11, "Healthy", "None", "N/A", "WR2"),
    ("Isaiah Grant", "RB", 28, "Healthy", "None", "N/A", "RB2"),
    ("Cole Hansen", "OT", 68, "Healthy", "None", "N/A", "OT2"),
    ("Malik Price", "DE", 95, "Healthy", "None", "N/A", "DE2")
]

def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_roster_table():
    """Verifies and initializes the roster tracking data table matrix."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS team_roster (
        player_id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_name TEXT NOT NULL,
        position TEXT NOT NULL,
        jersey_num INTEGER,
        health_status TEXT NOT NULL, -- 'Healthy', 'Probable', 'Questionable', 'Doubtful', 'Out'
        injury_type TEXT DEFAULT 'None',
        duration_weeks TEXT DEFAULT 'N/A',
        depth_slot TEXT, -- e.g. 'QB1', 'WR2'
        save_id TEXT -- player id from the game save; NULL for placeholder players
    )
    """)

    # Check if empty, then seed initial sample roster states
    cursor.execute("SELECT COUNT(*) FROM team_roster")
    if cursor.fetchone()[0] == 0:
        initial_roster = [
            ("Broderick Donahue", "WR", 1, "Healthy", "None", "N/A"),
            ("Kaleb Vance", "QB", 12, "Healthy", "None", "N/A"),
            ("Tyler Cross", "RB", 22, "Questionable", "Ankle Sprain", "1-2 Weeks"),
            ("Marcus Miller", "OT", 74, "Out", "Torn Meniscus", "Season"),
            ("Jalen Brooks", "DE", 90, "Probable", "Bruised Ribs", "Day-to-Day")
        ]
        cursor.executemany("""
        INSERT INTO team_roster (player_name, position, jersey_num, health_status, injury_type, duration_weeks)
        VALUES (?, ?, ?, ?, ?, ?)
        """, initial_roster)

    # Add the depth chart column to rosters created before it existed
    existing_cols = [col[1] for col in cursor.execute("PRAGMA table_info(team_roster)").fetchall()]
    if "depth_slot" not in existing_cols:
        cursor.execute("ALTER TABLE team_roster ADD COLUMN depth_slot TEXT")
    if "save_id" not in existing_cols:
        cursor.execute("ALTER TABLE team_roster ADD COLUMN save_id TEXT")
    # Player details shown on the depth chart tab
    for col, col_type in (("overall", "INTEGER"), ("class_year", "TEXT"), ("height_in", "INTEGER"), ("weight_lb", "INTEGER"), ("portrait_file", "TEXT")):
        if col not in existing_cols:
            cursor.execute(f"ALTER TABLE team_roster ADD COLUMN {col} {col_type}")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_team_roster_save_id ON team_roster(save_id)")
    
    # Per-game stat lines from the save, merged across stat types (offense, defense, kicking...)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS player_game_stats (
        save_id TEXT NOT NULL,
        week_num INTEGER NOT NULL,
        stats_json TEXT NOT NULL,
        PRIMARY KEY (save_id, week_num)
    )
    """)

    # Fill in a starting depth chart if none has been set yet
    cursor.execute("SELECT COUNT(*) FROM team_roster WHERE depth_slot IS NOT NULL")
    if cursor.fetchone()[0] == 0:
        for name, slot in DEFAULT_DEPTH_SLOTS.items():
            cursor.execute("UPDATE team_roster SET depth_slot = ? WHERE player_name = ?", (slot, name))
        cursor.executemany("""
        INSERT INTO team_roster (player_name, position, jersey_num, health_status, injury_type, duration_weeks, depth_slot)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, BACKUP_PLAYERS)

    conn.commit()
    conn.close()

def query_injury_report():
    """Fetches all players who are not 100% healthy."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM team_roster WHERE health_status != 'Healthy' ORDER BY player_id ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def query_full_roster():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM team_roster ORDER BY position ASC, depth_slot ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def query_player(player_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM team_roster WHERE player_id = ?", (player_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def swap_depth_slots(player_a_id, player_b_id):
    """Swaps two players' depth chart slots (e.g. promotes WR2 to WR1)."""
    player_a = query_player(player_a_id)
    player_b = query_player(player_b_id)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE team_roster SET depth_slot = ? WHERE player_id = ?", (player_b['depth_slot'], player_a_id))
    cursor.execute("UPDATE team_roster SET depth_slot = ? WHERE player_id = ?", (player_a['depth_slot'], player_b_id))
    conn.commit()
    conn.close()

# Order of position groups on the depth chart tab
DEPTH_CHART_ORDER = ["QB", "HB", "FB", "WR", "TE", "LT", "LG", "C", "RG", "RT",
                     "LE", "RE", "DT", "LOLB", "MLB", "ROLB", "CB", "FS", "SS", "K", "P"]

def query_depth_chart(last_played_week=None):
    """Every player grouped by position in depth chart order, each with his latest game's stat line."""
    stats = query_week_stats(last_played_week) if last_played_week else {}
    order = lambda p: (DEPTH_CHART_ORDER.index(p['position']) if p['position'] in DEPTH_CHART_ORDER else len(DEPTH_CHART_ORDER),
                       int(re.sub(r"\D", "", p['depth_slot'] or "") or 99))
    players = sorted(query_full_roster(), key=order)
    for p in players:
        p['stat_line'] = format_stat_line(stats.get(p['save_id']))
        p['position_name'] = POSITION_NAMES.get(p['position'], p['position'])
        p['portrait'] = media.portrait_url("player", p.get('portrait_file'))
    return players

def query_week_stats(week_num):
    """{save_id: stats dict} for every player who recorded stats in that week's game."""
    conn = get_connection()
    rows = conn.execute("SELECT save_id, stats_json FROM player_game_stats WHERE week_num = ?", (week_num,)).fetchall()
    conn.close()
    return {row['save_id']: json.loads(row['stats_json']) for row in rows}

def query_player_week_stats(save_id, week_num):
    conn = get_connection()
    row = conn.execute("SELECT stats_json FROM player_game_stats WHERE save_id = ? AND week_num = ?", (save_id, week_num)).fetchone()
    conn.close()
    return json.loads(row['stats_json']) if row else None

# Season leader boards: (title, stat that ranks them, how to show the number, supporting detail)
LEADER_CATEGORIES = [
    ("Passing", "PASSYARDS", "yds", lambda s: f"{s.get('PASSCOMPLETED', 0)}/{s.get('PASSATTEMPTS', 0)}, {s.get('PASSTDS', 0)} TD, {s.get('PASSINTS', 0)} INT"),
    ("Rushing", "RUSHYARDS", "yds", lambda s: f"{s.get('RUSHATTEMPTS', 0)} car, {s.get('RUSHTDS', 0)} TD"),
    ("Receiving", "RECEIVEYARDS", "yds", lambda s: f"{s.get('RECEIVECATCHES', 0)} rec, {s.get('RECEIVETDS', 0)} TD"),
    ("Tackles", "TACKLES", "tkl", lambda s: f"{s.get('DEFTACKLESFORLOSS', 0)} TFL, {s.get('DEFPASSDEFLECTIONS', 0)} PD"),
    ("Sacks", "SACKS", "sacks", lambda s: f"{s.get('DLINEFORCEDFUMBLES', 0)} FF, {s.get('DEFTACKLESFORLOSS', 0)} TFL"),
    ("Interceptions", "DSECINTS", "INT", lambda s: f"{s.get('DEFPASSDEFLECTIONS', 0)} PD, {s.get('DSECINTRETURNYARDS', 0)} ret yds"),
]
LEADERS_PER_CATEGORY = 3

def query_season_leaders():
    """[{title, unit, leaders: [{name, position, jersey, portrait, value, detail}]}] for our team this season."""
    conn = get_connection()
    rows = conn.execute("SELECT save_id, stats_json FROM player_game_stats").fetchall()
    conn.close()
    totals = {}
    for row in rows:
        bucket = totals.setdefault(row['save_id'], {})
        for key, value in json.loads(row['stats_json']).items():
            bucket[key] = max(bucket.get(key, 0), value) if key == 'GAMERATING' or 'LONGEST' in key else bucket.get(key, 0) + value
    for stats in totals.values():
        stats['TACKLES'] = stats.get('DEFTACKLES', 0) + stats.get('ASSDEFTACKLES', 0)
        stats['SACKS'] = stats.get('DLINESACKS', 0) + 0.5 * stats.get('DLINEHALFSACK', 0)
    players = {p['save_id']: p for p in query_full_roster() if p['save_id']}
    boards = []
    for title, key, unit, detail in LEADER_CATEGORIES:
        ranked = sorted((pid for pid in totals if pid in players and totals[pid].get(key, 0) > 0), key=lambda pid: -totals[pid][key])
        boards.append({"title": title, "unit": unit, "leaders": [
            {"name": players[pid]['player_name'], "position": players[pid]['position'], "jersey": players[pid]['jersey_num'],
             "portrait": media.portrait_url("player", players[pid].get('portrait_file')),
             "value": f"{totals[pid][key]:g}", "detail": detail(totals[pid])}
            for pid in ranked[:LEADERS_PER_CATEGORY]]})
    return boards

# Short labels for the page, plain English for AI prompts (models copy abbreviations like 'tkl' into prose)
STAT_LABELS = {
    "short": {"pass": "pass yds", "car": "car", "rush": "rush yds", "rec": "rec", "recyds": "rec yds", "td": "TD", "int": "INT",
              "tkl": "tkl", "sack": "sack", "pd": "PD", "ff": "FF", "fr": "FR", "fg": "FG", "xp": "XP", "pancakes": "pancakes",
              "ret": "ret", "retyds": "ret yds", "fumble": "fumble", "of": "/", "sep": "; "},
    "prose": {"pass": "passing yards", "car": "carries", "rush": "rushing yards", "rec": "catches", "recyds": "receiving yards",
              "td": "touchdowns", "int": "interceptions", "tkl": "tackles", "sack": "sacks", "pd": "pass deflections",
              "ff": "forced fumbles", "fr": "fumble recoveries", "fg": "field goals made", "xp": "extra points made", "pancakes": "pancake blocks",
              "ret": "returns", "retyds": "return yards", "fumble": "fumbles", "of": " of ", "sep": ", "}
}

POSITION_NAMES = {
    "QB": "quarterback", "HB": "running back", "FB": "fullback", "WR": "wide receiver", "TE": "tight end",
    "LT": "left tackle", "LG": "left guard", "C": "center", "RG": "right guard", "RT": "right tackle",
    "LE": "defensive end", "RE": "defensive end", "DT": "defensive tackle", "LOLB": "outside linebacker",
    "MLB": "middle linebacker", "ROLB": "outside linebacker", "CB": "cornerback", "FS": "free safety",
    "SS": "strong safety", "K": "kicker", "P": "punter"
}

def describe_player(player):
    """'backup running back Diore Hubbard' / 'starting quarterback Tyler Hughes' (no depth chart codes)."""
    position = POSITION_NAMES.get(player['position'], player['position'])
    starter = (player['depth_slot'] or "").endswith("1") and not (player['depth_slot'] or "")[-2:-1].isdigit()
    return f"{'starting' if starter else 'backup'} {position} {player['player_name']}"

def format_stat_line(stats, style="short"):
    """Save stat fields -> '19/29, 218 pass yds, 2 TD, 1 INT' (short) or plain English (prose). Empty if nothing notable."""
    if not stats:
        return ""
    L = STAT_LABELS[style]
    s = lambda key: stats.get(key, 0)
    with_tds = lambda text, tds: text + (f", {tds} {L['td']}" if tds else "")
    parts = []
    if s('PASSATTEMPTS'):
        parts.append(with_tds(f"{s('PASSCOMPLETED')}{L['of']}{s('PASSATTEMPTS')}, {s('PASSYARDS')} {L['pass']}", s('PASSTDS')) + (f", {s('PASSINTS')} {L['int']}" if s('PASSINTS') else ""))
    if s('RUSHATTEMPTS'):
        parts.append(with_tds(f"{s('RUSHATTEMPTS')} {L['car']}, {s('RUSHYARDS')} {L['rush']}", s('RUSHTDS')))
    if s('RECEIVECATCHES'):
        parts.append(with_tds(f"{s('RECEIVECATCHES')} {L['rec']}, {s('RECEIVEYARDS')} {L['recyds']}", s('RECEIVETDS')))
    if s('DEFTACKLES') or s('ASSDEFTACKLES'):
        parts.append(f"{s('DEFTACKLES') + s('ASSDEFTACKLES')} {L['tkl']}")
    sacks = s('DLINESACKS') + 0.5 * s('DLINEHALFSACK')
    if sacks:
        parts.append(f"{sacks:g} {L['sack']}")
    if s('DSECINTS'):
        parts.append(f"{s('DSECINTS')} {L['int']}")
    if s('DEFPASSDEFLECTIONS'):
        parts.append(f"{s('DEFPASSDEFLECTIONS')} {L['pd']}")
    if s('DLINEFORCEDFUMBLES'):
        parts.append(f"{s('DLINEFORCEDFUMBLES')} {L['ff']}")
    if s('DLINEFUMBLERECOVERIES'):
        parts.append(f"{s('DLINEFUMBLERECOVERIES')} {L['fr']}")
    if s('KICKFGATTEMPTS'):
        parts.append(f"{s('KICKFGMADE')}{L['of']}{s('KICKFGATTEMPTS')} {L['fg']}")
    if s('KICKEPATTEMPTS'):
        parts.append(f"{s('KICKEPMADE')}{L['of']}{s('KICKEPATTEMPTS')} {L['xp']}")
    if s('OLINEPANCAKES'):
        parts.append(f"{s('OLINEPANCAKES')} {L['pancakes']}")
    if s('KRETATTEMPTS') or s('PRETATTEMPTS'):
        parts.append(f"{s('KRETATTEMPTS') + s('PRETATTEMPTS')} {L['ret']}, {s('KRETYARDS') + s('PRETYARDS')} {L['retyds']}")
    if s('RUSHFUMBLES'):
        parts.append(f"{s('RUSHFUMBLES')} {L['fumble']}")
    return L['sep'].join(parts)

# Run initialization automatically on script import
initialize_roster_table()
