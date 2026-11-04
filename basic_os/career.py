"""The head coach's career in this dynasty: every season, at which school, with its record and big moments. When a sync
shows him at a different school than last time (he took another job), the move is recorded, and from then on the
writers know where he came from: the dispatch, the campus feed, the press room, the podcast and the players.

Like in real life, his past comes up a lot while he's new (his first games at the new school), every time he faces a
school he used to coach, and only now and then after that."""
import json
import random
import time
import database
import league

NEW_FOR_GAMES = 4       # his first games at a new school: everyone still talks about where he came from
MENTION_CHANCE = 0.3    # after that, how often a piece of writing brings up his past

def initialize_tables():
    conn = database.get_db_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS coach_career (
        season_year INTEGER NOT NULL,
        team_id INTEGER NOT NULL,
        short_name TEXT,
        name TEXT,
        nickname TEXT,
        conference TEXT,
        wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,
        coached INTEGER DEFAULT 1,     -- 0: he arrived after this school's season was played (someone else coached it)
        highlights_json TEXT,
        last_seen REAL,
        PRIMARY KEY (season_year, team_id)
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS coach_moves (
        move_id INTEGER PRIMARY KEY AUTOINCREMENT,
        season_year INTEGER,
        week INTEGER,
        from_team_id INTEGER, from_name TEXT,
        to_team_id INTEGER, to_name TEXT,
        welcomed INTEGER DEFAULT 0,
        created_at REAL
    )
    """)
    conn.commit()
    conn.close()

initialize_tables()

def full_name(row):
    return f"{row.get('name') or ''} {row.get('nickname') or ''}".strip()

def coach_name():
    staff = (league.query_user_team() or {}).get('staff') or {}
    return (staff.get('hc') or {}).get('name') or "the head coach"

def rows():
    return league.query_rows("SELECT * FROM coach_career ORDER BY season_year, last_seen")

def latest_move():
    found = league.query_rows("SELECT * FROM coach_moves ORDER BY move_id DESC LIMIT 1")
    return found[0] if found else None

# ---------- Recording (every sync) ----------

def season_highlights(season):
    """This season's big moments at the current school ("2026 Mountain West Championship Game: won 31-24 over UNLV")."""
    import lore
    return [line for line in lore.dynasty_title_games() + lore.dynasty_postseason() if line.startswith(str(season))]

def record(season, week):
    """Called after each sync, once the schedule, league and care are up to date. Returns the move if he just changed schools."""
    us = league.query_user_team()
    if not us or season is None:
        return None
    season = int(season)
    history = rows()
    last = max(history, key=lambda r: r['last_seen']) if history else None
    move = None
    conn = database.get_db_connection()
    if last and last['team_id'] != us['team_id']:
        conn.execute("INSERT INTO coach_moves (season_year, week, from_team_id, from_name, to_team_id, to_name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (season, week, last['team_id'], full_name(last), us['team_id'], full_name(us), time.time()))
        move = {"from": full_name(last), "to": full_name(us)}
    mine = next((r for r in history if r['season_year'] == season and r['team_id'] == us['team_id']), None)
    if mine is None:
        # Taking over after the new school already played its season (the carousel comes after the bowls): that
        # season is someone else's, so it doesn't count toward his record
        played = conn.execute("SELECT COUNT(*) FROM schedule_tracking WHERE is_played = 1").fetchone()[0]
        coached = 0 if (move and played) else 1
        conn.execute("""INSERT INTO coach_career (season_year, team_id, short_name, name, nickname, conference, coached, last_seen)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (season, us['team_id'], us.get('short_name'), us['name'], us.get('nickname'),
                                                             us.get('conference'), coached, time.time()))
    else:
        conn.execute("UPDATE coach_career SET last_seen = ? WHERE season_year = ? AND team_id = ?", (time.time(), season, us['team_id']))
        coached = mine['coached']
    conn.commit()
    conn.close()
    if coached:
        wins, losses = database.query_season_record()
        conn = database.get_db_connection()
        conn.execute("UPDATE coach_career SET wins = ?, losses = ?, highlights_json = ? WHERE season_year = ? AND team_id = ?",
                     (wins, losses, json.dumps(season_highlights(season)), season, us['team_id']))
        conn.commit()
        conn.close()
    if move:
        welcome(us, move)
    return move

def welcome(us, move):
    """The new athletic director's first email: the coach's phone knows he has a new job."""
    import care
    week = int(care.get_state("week") or 0)
    conn = database.get_db_connection()
    conn.execute("INSERT INTO care_emails (week, sender, subject, body, actions_json) VALUES (?, 'ad', ?, ?, '[]')",
                 (week, f"Welcome to {us['name']}",
                  f"Coach, welcome to {full_name(us)} football. Everybody here saw what you built at {move['from']}, and that's exactly why "
                  "you're here. The players are eager to meet you, the boosters already want dinner, and the fans are buzzing. "
                  "Let's get to work."))
    conn.execute("UPDATE coach_moves SET welcomed = 1 WHERE welcomed = 0")
    conn.commit()
    conn.close()

# ---------- What the writers know ----------

def stints():
    """His stops in order, each [{team, short, team_id, years, wins, losses, highlights}], seasons he coached only."""
    out = []
    for r in rows():
        if not r['coached']:
            continue
        if out and out[-1]['team_id'] == r['team_id']:
            stop = out[-1]
        else:
            stop = {"team": full_name(r), "short": r['short_name'], "team_id": r['team_id'], "years": [], "wins": 0, "losses": 0, "highlights": []}
            out.append(stop)
        stop['years'].append(r['season_year'])
        stop['wins'] += r['wins'] or 0
        stop['losses'] += r['losses'] or 0
        stop['highlights'] += json.loads(r['highlights_json'] or "[]")
    return out

def years_here():
    """The seasons he has coached at his current school (empty before the first sync)."""
    us = league.query_user_team() or {}
    here = stints()
    return here[-1]['years'] if here and here[-1]['team_id'] == us.get('team_id') else []

def coached_season(season):
    """Whether he coached his current school in `season` (True when nothing is recorded yet, so older data still counts)."""
    us = league.query_user_team() or {}
    mine = [r for r in rows() if r['team_id'] == us.get('team_id')]
    if not mine:
        return True
    return any(r['season_year'] == int(season) and r['coached'] for r in mine)

def past_stops():
    """Every stop before the current one (a return to an old school keeps the earlier stint as a past stop)."""
    us = league.query_user_team() or {}
    stops = stints()
    return stops[:-1] if stops and stops[-1]['team_id'] == us.get('team_id') else stops

def describe(stop):
    years = f"{stop['years'][0]}" if len(stop['years']) == 1 else f"{stop['years'][0]}-{stop['years'][-1]}"
    seasons = f"{len(stop['years'])} season{'s' if len(stop['years']) != 1 else ''}"
    line = f"{stop['team']} ({years}, {seasons}, went {stop['wins']}-{stop['losses']}"
    return line + (f"; {'; '.join(stop['highlights'])}" if stop['highlights'] else "") + ")"

def games_here():
    """Games he has coached at his current school, counted up to NEW_FOR_GAMES (later seasons don't need the exact number)."""
    years = years_here()
    if not years:
        return 0          # hired after this school's season: the games on the schedule were someone else's
    if len(years) > 1:
        return NEW_FOR_GAMES
    wins, losses = database.query_season_record()
    return wins + losses

def former_team(opponent_name):
    """The past stop this opponent is ("Wyoming Cowboys" vs "Wyoming"), or None."""
    name = (opponent_name or "").lower()
    return next((s for s in past_stops() if name and (s['team'].lower() in name or name in s['team'].lower())), None)

def context(opponent=None, audience="media", rng=None):
    """A fact block for prompts about his past jobs, or "" when there's nothing to say this time. `audience` is "media"
    (dispatch, feed, press room, podcast) or "players" (his own locker room)."""
    past = past_stops()
    if not past:
        return ""
    us = league.query_user_team() or {}
    coach = coach_name()
    resume = "; ".join(describe(s) for s in past)
    reunion = former_team(opponent)
    new = games_here() < NEW_FOR_GAMES
    if reunion:
        return (f" Coach's past (a huge storyline this week): head coach {coach} used to coach {reunion['team']}, this week's opponent: "
                f"{describe(reunion)}. It's his first time facing them since he left, his old players are on the other sideline, and "
                f"their fans have feelings about him leaving." + (f" His full career: {resume}." if len(past) > 1 else ""))
    if new:
        lead = (f" The players know their new head coach {coach} just arrived from" if audience == "players"
                else f" Coach's past (people are still getting to know him, so it comes up a lot): head coach {coach} is new at {us.get('name')}, hired from")
        return f"{lead} {past[-1]['team']}. His career before this: {resume}."
    if (rng or random).random() >= MENTION_CHANCE:
        return ""
    return (f" Coach's past (bring it up only if it fits naturally, at most once): before {us.get('name')}, head coach {coach} coached {resume}.")
