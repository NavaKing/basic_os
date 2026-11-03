import json
import os
import re
import shutil
import subprocess
import threading
import backups
import care
import history
import database
import league
import roster
import media
import recruiting

# The dynasty save to follow. The game also writes "<save>-AUTOSAVE"; whichever is newer is used.
SAVE_FILE = os.environ.get("DYNASTY_SAVE_FILE") or os.path.join(
    os.path.expanduser("~"), "Documents", "EA SPORTS College Football 27", "saves", "DYNASTY-WYOYEAR1")
# Node script that decodes the save with madden-franchise (see save_reader/)
READER_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "save_reader", "read_dynasty.mjs")
NODE_EXE = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"

def initialize_sync_table():
    conn = database.get_db_connection()
    conn.execute("CREATE TABLE IF NOT EXISTS sync_state (state_key TEXT PRIMARY KEY, state_value TEXT)")
    conn.commit()
    conn.close()

def get_state(key):
    conn = database.get_db_connection()
    row = conn.execute("SELECT state_value FROM sync_state WHERE state_key = ?", (key,)).fetchone()
    conn.close()
    return row['state_value'] if row else None

def set_state(key, value):
    conn = database.get_db_connection()
    conn.execute("INSERT OR REPLACE INTO sync_state (state_key, state_value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def newest_save():
    candidates = [path for path in (SAVE_FILE, SAVE_FILE + "-AUTOSAVE") if os.path.exists(path)]
    return max(candidates, key=os.path.getmtime) if candidates else None

def read_save(save_path):
    """Runs the Node save reader and returns its JSON output (schedule, roster, depth chart)."""
    result = subprocess.run([NODE_EXE, READER_SCRIPT, save_path], capture_output=True, text=True, encoding="utf-8", timeout=120)
    if result.returncode != 0:
        # Node ends crash output with its version line, so report the actual error line instead
        error_lines = [line.strip() for line in result.stderr.splitlines() if "Error" in line]
        raise RuntimeError(error_lines[0] if error_lines else f"save reader exited with code {result.returncode}")
    return json.loads(result.stdout)

# Page loads run in parallel; only one may sync at a time. The others wait, then find the save already synced.
_sync_lock = threading.Lock()

def sync_if_changed():
    """Re-imports the schedule and roster whenever the save changes. Returns a short status line for the page."""
    with _sync_lock:
        return _sync_if_changed()

def _sync_if_changed():
    save_path = newest_save()
    if not save_path:
        return get_state('status') or f"Save sync unavailable: {os.path.basename(SAVE_FILE)} not found."
    save_version = f"{save_path}|{os.path.getmtime(save_path)}"
    if save_version == get_state('save_version'):
        return get_state('status')

    try:
        dynasty = read_save(save_path)
        if get_state('save_version'):  # nothing worth keeping before the first sync
            backups.create_backup(backups.AUTO_LABEL)
        sync_schedule(dynasty)
        sync_roster(dynasty)
        league.sync_league(dynasty['league'], dynasty['currentWeek'], dynasty.get('phase'))
        league.sync_plan_rosters(dynasty.get('planRosters'))
        league.sync_scoring(dynasty.get('scoringSummaries'))
        league.sync_rivalries(dynasty.get('rivalries'))
        history.sync(dynasty)
        care.advance(care.current_week())  # the week of our next game, now that the schedule is synced
        recruiting.sync_recruiting(dynasty.get('recruiting'), dynasty['league']['userTeamId'], dynasty['currentWeek'])
    except Exception as e:
        # The version isn't stored, so the next page load tries again (e.g. if the game was mid-write)
        return f"Save sync failed, showing last synced data: {e}"

    set_state('phase', json.dumps({**(dynasty.get('phase') or {}), "week": dynasty['currentWeek']}))
    set_state('departures', json.dumps(dynasty.get('departures') or {}))
    status = f"Synced from {dynasty['source']} · Week {dynasty['currentWeek']}"
    set_state('save_version', save_version)
    set_state('status', status)
    return status

def sync_schedule(dynasty):
    rows = []
    for g in dynasty['schedule']:
        wyo_stats = g['teamStats'] or {}
        opp_stats = g['opponentStats'] or {}
        rows.append((
            g['week'],
            f"{g['opponent']} {g['opponentNickname']}".strip(),
            1 if g['played'] else 0,
            wyo_stats.get('rushingYards', 0),
            wyo_stats.get('passingYards', 0),
            opp_stats.get('rushingYards', 0),
            opp_stats.get('passingYards', 0),
            "TBD",
            g['teamScore'],
            g['opponentScore'],
            g.get('site'),
            g.get('date'),
            g.get('kickoffMinutes'),
            g.get('network'),
            (g.get('weather') or {}).get('condition'),
            (g.get('weather') or {}).get('temperature'),
            (g.get('weather') or {}).get('precipitationChance'),
            (g.get('weather') or {}).get('wind'),
            (g.get('weather') or {}).get('windSpeed')
        ))

    conn = database.get_db_connection()
    conn.execute("DELETE FROM schedule_tracking")
    conn.executemany("""
        INSERT OR REPLACE INTO schedule_tracking (week_id, opponent_name, is_played, wyo_rush_yds, wyo_pass_yds, opp_rush_yds, opp_pass_yds, game_mvp, wyo_score, opp_score,
                                                  site, game_date, kickoff_minutes, network, weather, temperature, precip_chance, wind, wind_speed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, rows)
    conn.commit()
    conn.close()

def map_injury(player):
    """Save injury fields -> (health_status, injury_type, duration_weeks) in the app's vocabulary."""
    if player.get('injuryStatus', 'Uninjured') == 'Uninjured':
        return "Healthy", "None", "N/A"
    injury_type = re.sub(r"(?<!^)(?=[A-Z])", " ", player.get('injuryType') or "") or "Injury"  # 'HandBroken' -> 'Hand Broken'
    severity = player.get('injurySeverity') or ""
    if "Season" in severity:
        return "Out", injury_type, "Season"
    low, high = player.get('minInjuryDuration'), player.get('maxInjuryDuration')
    duration = f"{low}-{high} Games" if low and high and low != high else f"{high or low or '?'} Games"
    return ("Questionable" if severity == "CoupleGames" else "Out"), injury_type, duration

def sync_roster(dynasty):
    players = dynasty['roster']
    position_by_id = {p['id']: p['position'] for p in players}

    # Each player's place on their own position's depth chart (the chart only lists the top few)
    chart_order = {}
    for position, chart in dynasty['depthChart'].items():
        same_position = [player_id for player_id in chart if position_by_id.get(player_id) == position]
        for index, player_id in enumerate(same_position):
            chart_order.setdefault(player_id, index)

    by_position = {}
    for p in players:
        by_position.setdefault(p['position'], []).append(p)

    rows = []
    for position, group in by_position.items():
        # Charted players first in chart order, then the rest of the position by overall rating.
        # Name and id break ties so slots stay stable between syncs (a slot change ends storylines).
        group.sort(key=lambda p: (p['id'] not in chart_order, chart_order.get(p['id'], 0), -(p.get('overall') or 0), p['name'], p['id']))
        for rank, p in enumerate(group, start=1):
            health_status, injury_type, duration = map_injury(p)
            rows.append((p['id'], p['name'], position, p.get('jersey'), health_status, injury_type, duration, f"{position}{rank}",
                         p.get('overall'), p.get('classYear'), p.get('heightInches'), p.get('weightPounds'),
                         media.player_portrait_file(p.get('assetName'), p.get('headAsset')),
                         p.get('redshirt'), p.get('transferChance'), p.get('goProChance'),
                         p.get('hometown'), p.get('homeState'), p.get('stars'), p.get('devTrait'), p.get('nil'), int(bool(p.get('captain'))),
                         json.dumps(p.get('traits') or []), p.get('confidence'), p.get('hotCold')))

    conn = roster.get_connection()
    # Drop placeholder players and anyone who has left the team in the save
    synced_ids = [row[0] for row in rows]
    conn.execute(f"DELETE FROM team_roster WHERE save_id IS NULL OR save_id NOT IN ({','.join('?' * len(synced_ids))})", synced_ids)
    conn.executemany("""
        INSERT INTO team_roster (save_id, player_name, position, jersey_num, health_status, injury_type, duration_weeks, depth_slot,
                                 overall, class_year, height_in, weight_lb, portrait_file, redshirt, transfer_chance, go_pro_chance,
                                 hometown, home_state, stars, dev_trait, nil_value, captain, traits_json, confidence, hot_cold)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(save_id) DO UPDATE SET
            player_name = excluded.player_name, position = excluded.position, jersey_num = excluded.jersey_num,
            health_status = excluded.health_status, injury_type = excluded.injury_type,
            duration_weeks = excluded.duration_weeks, depth_slot = excluded.depth_slot,
            overall = excluded.overall, class_year = excluded.class_year, height_in = excluded.height_in, weight_lb = excluded.weight_lb,
            portrait_file = excluded.portrait_file, redshirt = excluded.redshirt,
            transfer_chance = excluded.transfer_chance, go_pro_chance = excluded.go_pro_chance,
            hometown = excluded.hometown, home_state = excluded.home_state, stars = excluded.stars,
            dev_trait = excluded.dev_trait, nil_value = excluded.nil_value, captain = excluded.captain,
            traits_json = excluded.traits_json, confidence = excluded.confidence, hot_cold = excluded.hot_cold
    """, rows)
    
    # Replace this season's stat lines; a player can have several records per game (e.g. offense + returns)
    stat_rows = {}
    for p in players:
        for game in p.get('gameStats', []):
            merged = stat_rows.setdefault((p['id'], game['week']), {})
            for key, value in game['stats'].items():
                merged[key] = max(merged.get(key, 0), value) if key == 'GAMERATING' or 'LONGEST' in key else merged.get(key, 0) + value
    conn.execute("DELETE FROM player_game_stats")
    conn.executemany("INSERT INTO player_game_stats (save_id, week_num, stats_json) VALUES (?, ?, ?)",
                     [(save_id, week, json.dumps(stats)) for (save_id, week), stats in stat_rows.items()])
    conn.commit()
    conn.close()

# Auto-initialize when save_sync.py gets imported by app.py
initialize_sync_table()
