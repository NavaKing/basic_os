import json
import database
import league
import roster
import team

# Dynasty history: the school record book from the save (with our players chasing it), the program's year-by-year
# history, and the app's own archive of every season's games and stat lines. The save only holds the current
# season's games, so the archive is what keeps past seasons: it is filled at every sync and never cleared.

# The save's record categories -> (our stat key, words)
RECORD_STATS = {
    "PassYards": ("PASSYARDS", "Passing yards"), "PassTds": ("PASSTDS", "Passing touchdowns"),
    "RushYards": ("RUSHYARDS", "Rushing yards"), "RushTds": ("RUSHTDS", "Rushing touchdowns"),
    "ReceiveCatches": ("RECEIVECATCHES", "Catches"), "ReceiveYards": ("RECEIVEYARDS", "Receiving yards"),
    "ReceiveTDs": ("RECEIVETDS", "Receiving touchdowns"), "DefensiveSacks": ("SACKS", "Sacks"), "DefensiveInts": ("DSECINTS", "Interceptions"),
}
SCOPES = ("game", "season", "career")
REGULAR_SEASON_GAMES = 12

def initialize_history_tables():
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS program_records (
        scope TEXT NOT NULL,            -- game, season, career
        stat TEXT NOT NULL,             -- the save's category, e.g. RushYards
        value REAL,
        year INTEGER,
        name TEXT,
        position TEXT,
        PRIMARY KEY (scope, stat)
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS program_seasons (
        year INTEGER PRIMARY KEY,
        wins INTEGER, losses INTEGER, ties INTEGER, conf_wins INTEGER, conf_losses INTEGER,
        conference TEXT, conf_standing INTEGER, final_rank INTEGER, coach TEXT, bowls_json TEXT
    )
    """)
    # The archive: never cleared, so past seasons survive the save moving on
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS history_games (
        season_year INTEGER NOT NULL,
        week INTEGER NOT NULL,
        opponent_name TEXT,
        site TEXT,
        our_score INTEGER,
        their_score INTEGER,
        PRIMARY KEY (season_year, week)
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS history_player_games (
        season_year INTEGER NOT NULL,
        week INTEGER NOT NULL,
        save_id TEXT NOT NULL,
        name TEXT,
        position TEXT,
        stats_json TEXT NOT NULL,
        PRIMARY KEY (season_year, week, save_id)
    )
    """)
    conn.commit()
    conn.close()

# ---------- Sync ----------

def sync(dynasty):
    """Called after the schedule and roster are synced: stores the record book and history, and archives this season."""
    season = (dynasty.get('phase') or {}).get('seasonYear')
    conn = database.get_db_connection()
    if dynasty.get('programRecords') is not None:
        conn.execute("DELETE FROM program_records")
        conn.executemany("INSERT OR REPLACE INTO program_records (scope, stat, value, year, name, position) VALUES (?, ?, ?, ?, ?, ?)",
                         [(r['scope'], r['stat'], r['value'], r['year'], r['name'], r['position']) for r in dynasty['programRecords']])
    conn.executemany("""INSERT OR REPLACE INTO program_seasons (year, wins, losses, ties, conf_wins, conf_losses, conference, conf_standing,
                                                                final_rank, coach, bowls_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                     [(h['year'], h['wins'], h['losses'], h['ties'], h['confWins'], h['confLosses'], h['conference'], h['confStanding'],
                       h['finalRank'], h['coach'], json.dumps(h['bowls'])) for h in dynasty.get('programHistory') or []])
    if season:
        conn.executemany("INSERT OR REPLACE INTO history_games (season_year, week, opponent_name, site, our_score, their_score) VALUES (?, ?, ?, ?, ?, ?)",
                         [(season, g['week_id'], g['opponent_name'], g['site'], g['wyo_score'], g['opp_score'])
                          for g in database.query_full_schedule() if g['is_played'] and g['wyo_score'] is not None])
        players = {p['save_id']: p for p in roster.query_full_roster() if p.get('save_id')}
        rows = conn.execute("SELECT save_id, week_num, stats_json FROM player_game_stats").fetchall()
        conn.executemany("INSERT OR REPLACE INTO history_player_games (season_year, week, save_id, name, position, stats_json) VALUES (?, ?, ?, ?, ?, ?)",
                         [(season, r['week_num'], r['save_id'], players[r['save_id']]['player_name'], players[r['save_id']]['position'], r['stats_json'])
                          for r in rows if r['save_id'] in players])
    conn.commit()
    conn.close()

# ---------- Stats ----------

def stat_value(stats, key):
    if key == "SACKS":
        return stats.get('DLINESACKS', 0) + 0.5 * stats.get('DLINEHALFSACK', 0)
    return stats.get(key, 0)

def number(value):
    return int(value) if float(value).is_integer() else round(value, 1)

def archived_lines():
    return [{**r, "stats": json.loads(r['stats_json'])} for r in league.query_rows("SELECT * FROM history_player_games")]

def current_season():
    rows = league.query_rows("SELECT MAX(season_year) AS year FROM history_games")
    return rows[0]['year'] if rows and rows[0]['year'] else None

# ---------- Record book and record watch ----------

def best_by_player(lines, key):
    """{save_id: (total, name, position, games)} summed over the given stat lines."""
    totals = {}
    for line in lines:
        total, _, _, games = totals.get(line['save_id'], (0, None, None, 0))
        totals[line['save_id']] = (total + stat_value(line['stats'], key), line['name'], line['position'], games + 1)
    return totals

def chaser(scope, key, lines, season):
    """Our best current mark against a record: a single game (any dynasty season), this season, or a career in the dynasty."""
    if scope == "game":
        best = max(lines, key=lambda l: stat_value(l['stats'], key), default=None)
        if not best or not stat_value(best['stats'], key):
            return None
        return {"name": best['name'], "position": best['position'], "value": stat_value(best['stats'], key),
                "when": f"{best['season_year']}, Week {best['week']}"}
    pool = [l for l in lines if l['season_year'] == season] if scope == "season" else lines
    totals = best_by_player(pool, key)
    if not totals:
        return None
    save_id, (value, name, position, games) = max(totals.items(), key=lambda item: item[1][0])
    if not value:
        return None
    out = {"name": name, "position": position, "value": value, "when": f"{season} season" if scope == "season" else "dynasty career"}
    if scope == "season" and games:
        out['pace'] = value / games * REGULAR_SEASON_GAMES
    return out

def record_book():
    records = {(r['scope'], r['stat']): r for r in league.query_rows("SELECT * FROM program_records")}
    lines = archived_lines()
    season = current_season()
    rows = []
    for stat, (key, label) in RECORD_STATS.items():
        cells = []
        for scope in SCOPES:
            record = records.get((scope, stat))
            ours = chaser(scope, key, lines, season)
            cell = {"scope": scope, "record": None, "ours": None}
            if record:
                cell['record'] = {"value": number(record['value']), "name": record['name'], "position": record['position'], "year": record['year']}
            if ours:
                cell['ours'] = {**ours, "value": number(ours['value'])}
                if record and record['value']:
                    cell['ours']['pct'] = min(100, round(100 * ours['value'] / record['value']))
                    cell['ours']['broken'] = ours['value'] > record['value']
                    if ours.get('pace'):
                        cell['ours']['pace'] = number(round(ours['pace']))
                        cell['ours']['on_pace'] = ours['pace'] > record['value']
            cells.append(cell)
        rows.append({"label": label, "cells": cells})
    return rows

# ---------- Year by year and dynasty bests ----------

def seasons():
    rows = league.query_rows("SELECT * FROM program_seasons ORDER BY year DESC")
    return [{"year": r['year'], "record": f"{r['wins']}-{r['losses']}" + (f"-{r['ties']}" if r['ties'] else ""),
             "conf": f"{r['conf_wins']}-{r['conf_losses']} {r['conference']}".strip(), "standing": r['conf_standing'],
             "rank": r['final_rank'] if r['final_rank'] and r['final_rank'] <= 25 else None, "coach": r['coach'],
             "bowls": [b.replace("_", " ") for b in json.loads(r['bowls_json'] or "[]")]} for r in rows]

def streaks(games):
    """Longest winning streak across the archived games, in order."""
    best = run = 0
    for g in sorted(games, key=lambda g: (g['season_year'], g['week'])):
        run = run + 1 if g['our_score'] > g['their_score'] else 0
        best = max(best, run)
    return best

def dynasty_bests():
    games = league.query_rows("SELECT * FROM history_games WHERE our_score IS NOT NULL")
    if not games:
        return None
    wins = [g for g in games if g['our_score'] > g['their_score']]
    describe = lambda g: {"text": f"{g['our_score']}-{g['their_score']} {'vs' if g['site'] != 'Away' else 'at'} {g['opponent_name']}",
                          "when": f"{g['season_year']}, Week {g['week']}"}
    season_count = len({g['season_year'] for g in games})
    team_bests = [("Dynasty record", {"text": f"{len(wins)}-{len(games) - len(wins)}", "when": f"{season_count} season{'s' if season_count != 1 else ''}"})]
    team_bests.append(("Most points", describe(max(games, key=lambda g: g['our_score']))))
    if wins:
        team_bests.append(("Biggest win", describe(max(wins, key=lambda g: g['our_score'] - g['their_score']))))
    team_bests.append(("Longest winning streak", {"text": f"{streaks(games)} games", "when": "across the dynasty"}))
    lines = archived_lines()
    performances = []
    for stat, (key, label) in RECORD_STATS.items():
        best = max(lines, key=lambda l: stat_value(l['stats'], key), default=None)
        if best and stat_value(best['stats'], key):
            performances.append({"label": label, "value": number(stat_value(best['stats'], key)), "name": best['name'],
                                 "position": best['position'], "when": f"{best['season_year']}, Week {best['week']}"})
    return {"team": [{"label": label, **value} for label, value in team_bests], "performances": performances}

# ---------- This week in dynasty history ----------

def this_week():
    game = database.query_active_week()
    season = current_season()
    if not game or season is None:
        return {"week": None, "games": []}
    rows = league.query_rows("SELECT * FROM history_games WHERE week = ? AND season_year < ? ORDER BY season_year DESC", (game['week_id'], season))
    return {"week": game['week_id'], "games": [{"year": r['season_year'], "opponent": r['opponent_name'], "site": r['site'],
                                                "result": "W" if r['our_score'] > r['their_score'] else ("L" if r['our_score'] < r['their_score'] else "T"),
                                                "score": f"{r['our_score']}-{r['their_score']}"} for r in rows]}

def build_page():
    us = team.user_team()
    return {"team": us['full_name'], "season": current_season(), "records": record_book(), "seasons": seasons(),
            "bests": dynasty_bests(), "this_week": this_week()}

initialize_history_tables()
