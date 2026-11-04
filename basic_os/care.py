import datetime
import hashlib
import json
import os
import random
import re
import database
import league
import media
import roster
import save_sync
import team

# Player care (first iteration, app-only: nothing is written to the game save). Each player has five needs that
# drain every week at a speed set by his persona and the calendar. Each week a care list of players who need you
# is drawn up, and you spend a budget of coach hours on them, ask a captain, or hand them to a position coach.
# Needs left low raise the chance of warning signs (missed curfew, falling behind in class...). Care builds trust.
# Every number comes from care_tuning.json. The rules below are pure functions, so the simulator can run whole
# fake seasons on them without touching the database.

TUNING_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "care_tuning.json")
NEEDS = ("morale", "academics", "home", "focus", "health")
NEED_LABELS = {"morale": "Morale", "academics": "Academics", "home": "Home life", "focus": "Focus", "health": "Health / rest"}
STARTERS = {"WR": 3, "DT": 2, "CB": 2}   # starting spots per save position (everything else has one)

# Warning signs by the need that's empty. Deliberately mild and blameless: they can be about any player, real or not.
WARNING_SIGNS = {
    "morale": ["Frustrated about his role; skipped optional film", "Quiet and withdrawn at practice all week"],
    "academics": ["Advisor flagged him as behind in two classes", "Missed a study hall session"],
    "home": ["Homesick; teammates say he's been calling home every night", "Asked twice about going home for a weekend"],
    "focus": ["Late to the team meeting", "Missed curfew on Thursday night"],
    "health": ["Trainers say he's running on empty", "Slept through a recovery session"],
}

# US states: name -> (abbreviation, census division), to judge how far a player is from home
STATES = {
    "Connecticut": ("CT", 1), "Maine": ("ME", 1), "Massachusetts": ("MA", 1), "NewHampshire": ("NH", 1), "RhodeIsland": ("RI", 1), "Vermont": ("VT", 1),
    "NewJersey": ("NJ", 2), "NewYork": ("NY", 2), "Pennsylvania": ("PA", 2),
    "Illinois": ("IL", 3), "Indiana": ("IN", 3), "Michigan": ("MI", 3), "Ohio": ("OH", 3), "Wisconsin": ("WI", 3),
    "Iowa": ("IA", 4), "Kansas": ("KS", 4), "Minnesota": ("MN", 4), "Missouri": ("MO", 4), "Nebraska": ("NE", 4), "NorthDakota": ("ND", 4), "SouthDakota": ("SD", 4),
    "Delaware": ("DE", 5), "Florida": ("FL", 5), "Georgia": ("GA", 5), "Maryland": ("MD", 5), "NorthCarolina": ("NC", 5), "SouthCarolina": ("SC", 5),
    "Virginia": ("VA", 5), "WestVirginia": ("WV", 5), "DistrictOfColumbia": ("DC", 5),
    "Alabama": ("AL", 6), "Kentucky": ("KY", 6), "Mississippi": ("MS", 6), "Tennessee": ("TN", 6),
    "Arkansas": ("AR", 7), "Louisiana": ("LA", 7), "Oklahoma": ("OK", 7), "Texas": ("TX", 7),
    "Arizona": ("AZ", 8), "Colorado": ("CO", 8), "Idaho": ("ID", 8), "Montana": ("MT", 8), "Nevada": ("NV", 8), "NewMexico": ("NM", 8), "Utah": ("UT", 8), "Wyoming": ("WY", 8),
    "Alaska": ("AK", 9), "California": ("CA", 9), "Hawaii": ("HI", 9), "Oregon": ("OR", 9), "Washington": ("WA", 9),
}

def load_tuning():
    with open(TUNING_FILE, encoding="utf-8") as f:
        tuning = json.load(f)
    preset = get_state("preset") or tuning["preset"]
    return {**tuning, "preset": preset, **tuning["presets"].get(preset, tuning["presets"][tuning["preset"]])}

# ---------- Storage ----------

def initialize_care_tables():
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS care_state (state_key TEXT PRIMARY KEY, state_value TEXT)")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS care_players (
        save_id TEXT PRIMARY KEY,
        needs_json TEXT NOT NULL,
        trust INTEGER NOT NULL,
        change_json TEXT
    )
    """)
    # change_json (how much each need moved in the last weekly update) came after the first release
    if "change_json" not in [col[1] for col in cursor.execute("PRAGMA table_info(care_players)").fetchall()]:
        cursor.execute("ALTER TABLE care_players ADD COLUMN change_json TEXT")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS care_warnings (
        warning_id INTEGER PRIMARY KEY AUTOINCREMENT,
        week INTEGER, save_id TEXT, need TEXT, text TEXT, open INTEGER DEFAULT 1
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS care_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        week INTEGER, save_id TEXT, kind TEXT, text TEXT
    )
    """)
    cursor.execute("CREATE TABLE IF NOT EXISTS care_council (save_id TEXT PRIMARY KEY)")
    cursor.execute("CREATE TABLE IF NOT EXISTS care_mentors (mentee TEXT PRIMARY KEY, mentor TEXT NOT NULL)")
    conn.commit()
    conn.close()

def get_state(key):
    rows = league.query_rows("SELECT state_value FROM care_state WHERE state_key = ?", (key,))
    return rows[0]['state_value'] if rows else None

def set_state(key, value):
    conn = database.get_db_connection()
    conn.execute("INSERT OR REPLACE INTO care_state (state_key, state_value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def log(week, save_id, kind, text):
    conn = database.get_db_connection()
    conn.execute("INSERT INTO care_log (week, save_id, kind, text) VALUES (?, ?, ?, ?)", (week, save_id, kind, text))
    conn.commit()
    conn.close()

# ---------- Players ----------

def home_distance(home_state, school_state):
    """0 in-state, 1 same region, 2 far from home (by US census division)."""
    home = STATES.get(re.sub(r"\s", "", home_state or ""))
    school = next((v for v in STATES.values() if v[0] == school_state), None)
    if not home or not school:
        return 1
    return 0 if home[0] == school[0] else (1 if home[1] == school[1] else 2)

def birthday_week(save_id):
    """The save has no real birthdays (nearly every player shares a placeholder), so each player gets a stable
    app-assigned week of the year; one in roughly every 52 has his birthday in any given week."""
    return int(hashlib.md5(save_id.encode("utf-8")).hexdigest(), 16) % 52

def temperament(save_id, spread):
    """{need: drain multiplier} unique to the player and stable all season (app-assigned: the save has nothing like it),
    so one player gets homesick easily and another loses focus first."""
    rng = random.Random(f"temperament-{save_id}")
    return {need: round(1 + rng.uniform(-spread, spread), 2) for need in NEEDS}

def start_needs(save_id, tuning):
    """Week-one needs: around start_need, different for each player so the care list isn't a tie."""
    rng = random.Random(f"start-{save_id}")
    return {need: round(tuning['start_need'] + rng.uniform(-tuning['start_spread'], tuning['start_spread'])) for need in NEEDS}

def depth_rank(player):
    digits = re.sub(r"\D", "", player.get('depth_slot') or "")
    return int(digits) if digits else 99

def roster_players():
    """Our players with what the care rules need to know about them."""
    us = team.user_team()
    school_state = (media.stadium_text(us.get('short')) or "").rsplit(", ", 1)[-1]
    players = [p for p in roster.query_full_roster() if p.get('save_id')]
    by_position = {}
    for p in players:
        by_position.setdefault(p['position'], []).append(p)
    out = []
    for group in by_position.values():
        group.sort(key=depth_rank)
        spots = STARTERS.get(group[0]['position'], 1)
        weakest = min((g['overall'] or 0) for g in group[:spots])
        for index, p in enumerate(group):
            out.append({
                "save_id": p['save_id'], "name": p['player_name'], "position": p['position'], "class": p.get('class_year') or "",
                "slot": p.get('depth_slot'),
                "overall": p.get('overall') or 0, "portrait": media.portrait_url("player", p.get('portrait_file')),
                "starter": index < spots, "blocked": index >= spots and (p.get('overall') or 0) >= weakest - 2,
                "injured": p.get('health_status') not in ("Healthy", None),
                "traits": json.loads(p.get('traits_json') or "[]"), "dev": (p.get('dev_trait') or "").replace("College_", ""),
                "distance": home_distance(p.get('home_state'), school_state), "hometown": p.get('hometown'),
                "confidence": p.get('confidence'), "hot_cold": p.get('hot_cold'), "birthday_week": birthday_week(p['save_id']),
                "temperament": temperament(p['save_id'], load_tuning()['temperament_spread']),
            })
    return out

# ---------- The rules (pure functions) ----------

def drain_for(player, ctx, tuning):
    """How much each need drops this week, before the staff's weekly support."""
    m = tuning['drain_modifiers']
    d = dict(tuning['drain'])
    d['morale'] += (m['loss_morale'] if ctx.get('lost') else 0) + (m['win_morale'] if ctx.get('won') else 0)
    d['morale'] += m['backup_rated_like_a_starter_morale'] if player['blocked'] else 0
    d['health'] += m['starter_health'] if player['starter'] else 0
    if player['injured']:
        d['health'] += m['injured_health']
        d['morale'] += m['injured_morale']
    d['academics'] += (m['exam_week_academics'] if ctx.get('exam') else 0) + (m['away_game_academics'] if ctx.get('away') else 0)
    d['home'] += {0: 0, 1: m['out_of_state_home'], 2: m['far_from_home_home']}[player['distance']]
    d['home'] += m['holiday_week_home'] if ctx.get('holiday') else 0
    d['focus'] += m['undisciplined_focus'] if "Undisciplined" in player['traits'] else 0
    d['focus'] += m['disciplined_focus'] if "Disciplined" in player['traits'] else 0
    d['focus'] += m['star_focus'] if player['dev'] in ("Star", "Elite") else 0
    d['focus'] += m['big_win_focus'] if ctx.get('big_win') else 0
    game = player.get('game')
    if game and not game['played']:   # on the bench all game: no hits taken, and less to stew over
        for need in ("morale", "focus"):
            d[need] *= tuning['game']['bench_drain_factor']
        d['health'] *= tuning['game']['bench_health_factor']
    trusting = 1 - tuning['trust_drain_relief'] * player['trust'] / 100  # a player who trusts the coach copes better
    return {need: max(0, d[need]) * tuning['drain_scale'] * player['temperament'][need] * trusting for need in NEEDS}

def game_boost(player, tuning):
    """What last week's game gives back: a standout game or a Player of the Week award lifts morale and focus (and an
    award, trust). Returns ({need: points}, trust points, label or None)."""
    game, g = player.get('game'), tuning['game']
    if not game or not game['played']:
        return {}, 0, None
    boost = {"morale": g['played_morale']}
    trust, label = 0, None
    if game['standout']:
        boost['morale'] += g['standout_morale']
        boost['focus'] = g['standout_focus']
        label = "standout game"
    if game['award'] == "national":
        boost['morale'] += g['player_of_week_morale']
        boost['focus'] = boost.get('focus', 0) + g['player_of_week_focus']
        trust, label = g['player_of_week_trust'], "Player of the Week"
    elif game['award'] == "conference":
        boost['morale'] += g['conference_player_of_week_morale']
        trust, label = g['conference_player_of_week_trust'], "Conference Player of the Week"
    return boost, trust, label

def warning_chance(player, ctx, tuning):
    """This week's chance of a warning sign: a small base, plus each low need (Focus counts double), scaled by persona,
    big wins, and trust. Players whose needs are fine almost never act out."""
    w = tuning['warning']
    chance = tuning['warning_chance']
    for need in NEEDS:
        if player['needs'][need] < tuning['low_need']:
            chance += w['low_need_chance'] + (w['low_focus_chance'] if need == "focus" else 0)
    factor = 1.0
    factor *= w['undisciplined'] if "Undisciplined" in player['traits'] else 1
    factor *= w['disciplined'] if "Disciplined" in player['traits'] else 1
    factor *= w['star'] if player['dev'] in ("Star", "Elite") else 1
    factor *= w['big_win'] if ctx.get('big_win') else 1
    factor *= 1 - w['trust_relief'] * player['trust'] / 100
    return min(w['max_chance'], chance * factor)

def pick_care_list(players, ctx, tuning, council):
    """The players who need the coach this week: lowest needs first, weighted by how much they matter."""
    def score(p):
        importance = 1.3 if p['starter'] else 1.0
        importance += 0.2 if p['save_id'] in council else 0
        importance += 0.2 if p['dev'] in ("Impact", "Star", "Elite") else 0
        urgency = (100 - min(p['needs'].values())) + 15 * len(p.get('warnings', [])) + (15 if p['birthday_week'] == ctx.get('week_of_year') else 0)
        return importance * urgency
    return [p['save_id'] for p in sorted(players, key=score, reverse=True)[:tuning['care_list_size']]]

def run_week(players, ctx, tuning, council, mentors, rng):
    """Drains needs, gives the staff's weekly support, applies mentors, captains and the calendar, and rolls warning
    signs. Mutates players; returns [(save_id or None, kind, text)] events."""
    events = []
    game_notes = []
    by_id = {p['save_id']: p for p in players}
    team_lift, reasons = team_boost(ctx, tuning)
    if team_lift:
        lifts = ", ".join(f"{NEED_LABELS[n].split(' /')[0].lower()} +{v}" for n, v in team_lift.items())
        events.append((None, "team", f"The team is riding {', '.join(reasons)}: everyone's {lifts}."))
    low_captains = [by_id[c] for c in council if c in by_id and by_id[c]['needs']['morale'] < tuning['council']['low_morale']]
    if low_captains:
        events.append((None, "council", f"{low_captains[0]['name']} is down, and the locker room feels it: everyone's morale drains faster this week."))
    for p in players:
        drain = drain_for(p, ctx, tuning)
        mentor = by_id.get(mentors.get(p['save_id']))
        if mentor:
            bad = "Undisciplined" in mentor['traits'] or mentor['needs']['focus'] < tuning['low_need']
            if bad:
                drain['focus'] *= tuning['mentor']['bad_pair_focus_factor']
            else:
                drain['morale'] *= tuning['mentor']['drain_factor']
                drain['focus'] *= tuning['mentor']['drain_factor']
                mentor['trust'] = min(100, mentor['trust'] + tuning['mentor']['mentor_trust_per_week'])
        if low_captains:
            drain['morale'] += tuning['council']['team_morale_drain']
        if ctx.get('senior_day') and p['class'] == "Senior":
            drain['morale'] -= tuning['senior_day_morale']
        boost, trust, label = game_boost(p, tuning)
        boost = {n: boost.get(n, 0) + team_lift.get(n, 0) for n in set(boost) | set(team_lift)}
        for need in NEEDS:
            pulled = p['needs'][need] - drain[need] + tuning['staff_rate'] * (tuning['staff_target'] - p['needs'][need])
            p['needs'][need] = round(max(0, min(100, pulled + boost.get(need, 0))), 1)
        p['trust'] = min(100, p['trust'] + trust)
        if label:
            game_notes.append((p, label, boost, trust))
        if rng(p['save_id']).random() < warning_chance(p, ctx, tuning):
            need = min(NEEDS, key=lambda n: p['needs'][n])
            text = rng(p['save_id'] + need).choice(WARNING_SIGNS[need])
            p.setdefault('warnings', []).append({"need": need, "text": text})
            events.append((p['save_id'], "warning", f"{p['name']}: {text} ({NEED_LABELS[need]} {round(p['needs'][need])})."))
    for p, label, boost, trust in game_notes:
        if label != "standout game":
            events.append((p['save_id'], "game", f"{p['name']} was named {label}: morale +{boost['morale']}" + (f", trust +{trust}" if trust else "") + "."))
    standouts = [p['name'] for p, label, _, _ in game_notes if label == "standout game"]
    if standouts:
        events.append((None, "game", f"Standout games lift morale and focus: {', '.join(standouts)}."))
    if ctx.get('senior_day'):
        events.append((None, "calendar", "Senior day: the seniors' morale gets a lift."))
    return events

def apply_action(player, action_key, need, tuning, ctx, council_member=None):
    """Fills a need and builds trust; returns a log line. Raises ValueError for an unknown action or need."""
    action = tuning['actions'].get(action_key)
    if not action or need not in NEEDS:
        raise ValueError("Unknown care action.")
    fills = action.get('fills') or [need]
    for n in fills:
        player['needs'][n] = min(100, player['needs'][n] + action['fill'])
    if action.get('focus_bonus') and "focus" not in fills:
        player['needs']['focus'] = min(100, player['needs']['focus'] + action['focus_bonus'])
    trust = action['trust'] + (tuning['birthday_trust_bonus'] if player['birthday_week'] == ctx.get('week_of_year') and action['trust'] else 0)
    player['trust'] = min(100, player['trust'] + trust)
    if action.get('clears_warnings'):
        player['warnings'] = []
    if council_member is not None:
        council_member['trust'] = min(100, council_member['trust'] + action.get('captain_trust', 0))
    who = f" via {council_member['name']}" if council_member is not None else ""
    return f"{action['label']}{who} with {player['name']}: {', '.join(NEED_LABELS[n] for n in fills)} +{action['fill']}" + (f", trust +{trust}" if trust else "")

# ---------- The week as the save sees it ----------

def week_context(week):
    """What shapes week `week`: last week's result and travel, exams, holidays, senior day."""
    tuning = load_tuning()
    schedule = {g['week_id']: g for g in database.query_full_schedule()}
    last, this = schedule.get(week - 1), schedule.get(week)
    ctx = {"week": week, "exam": week in tuning['calendar']['exam_weeks']}
    if last and last['is_played'] and last['wyo_score'] is not None:
        ctx['won'] = last['wyo_score'] > last['opp_score']
        ctx['lost'] = last['wyo_score'] < last['opp_score']
        ctx['away'] = last.get('site') == "Away"
        opponent = team.opponent(last['opponent_name'])
        rivals = {r['opponent_id'] for r in league.query_rivalries()}
        ranked = opponent and (league.query_poll(week - 2).get(opponent['id']) or 99) <= 25
        ctx['big_win'] = bool(ctx['won'] and opponent and (ranked or opponent['id'] in rivals))
    date = (this or {}).get('game_date') or (last or {}).get('game_date')
    if date:
        day = datetime.date.fromisoformat(date)
        ctx['week_of_year'] = day.isocalendar()[1] % 52
        md = day.strftime("%m-%d")
        ctx['holiday'] = any((start <= md <= end) if start <= end else (md >= start or md <= end) for start, end in tuning['calendar']['holiday_dates'])
    home_weeks = [w for w, g in schedule.items() if g.get('site') == "Home" and w <= 14]
    ctx['senior_day'] = bool(this and home_weeks and week == max(home_weeks))
    ctx.update(team_standing(week, schedule))
    return ctx

def team_standing(week, schedule):
    """The win streak going into `week`, our poll rank, and any ranking milestone reached for the first time this week
    (from the save's polls, so it needs no memory of its own)."""
    played = [g for w, g in sorted(schedule.items()) if w < week and g['is_played'] and g['wyo_score'] is not None]
    streak = 0
    for g in reversed(played):
        if g['wyo_score'] <= g['opp_score']:
            break
        streak += 1
    us = (league.query_user_team() or {}).get('team_id')
    rank = league.query_poll(week - 2).get(us) if us else None
    earlier = [r for r in (row['media_rank'] for row in league.query_rows(
        "SELECT media_rank FROM league_polls WHERE team_id = ? AND poll_week < ?", (us, week - 2))) if r]
    best_before = min(earlier) if earlier else 999
    out = {"streak": streak, "rank": rank if rank and rank <= 25 else None}
    if out['rank'] and best_before > 25:
        out['first_ranked'] = True
    for threshold in load_tuning()['team']['milestones']:
        if out['rank'] and out['rank'] <= threshold < best_before and best_before <= 25:
            out['milestone'] = threshold
    return out

def a_or_an(number):
    """'an' before 8, 11, 18 and 80-something ("an 11-game win streak"), 'a' otherwise."""
    return "an" if str(number).startswith("8") or number in (11, 18) else "a"

def team_boost(ctx, tuning):
    """What the team's success gives every player this week: ({need: points}, [reasons])."""
    t = tuning['team']
    boost, reasons = {}, []
    def add(need, points):
        boost[need] = boost.get(need, 0) + points
    if ctx.get('won'):
        add("morale", t['win_morale'])
        add("focus", t['win_focus'])
        reasons.append("the win")
    streak = ctx.get('streak', 0)
    if streak >= t['streak_from']:
        add("morale", min(t['streak_cap'], (streak - t['streak_from'] + 1) * t['streak_per_win']))
        reasons.append(f"{a_or_an(streak)} {streak}-game win streak")
    if ctx.get('rank'):
        add("morale", t['ranked_morale'])
        reasons.append(f"being ranked No. {ctx['rank']}")
    if ctx.get('first_ranked'):
        add("morale", t['first_ranked_morale'])
        add("focus", t['first_ranked_focus'])
        reasons.append("cracking the poll for the first time")
    elif ctx.get('milestone'):
        add("morale", t['milestone_morale'])
        reasons.append("the No. 1 ranking" if ctx['milestone'] == 1 else f"cracking the top {ctx['milestone']}")
    return boost, reasons

def game_results(week, tuning):
    """{save_id: {"played", "standout", "award"}} for our game in `week`, or {} when there was no game (a bye, or
    the save hasn't written the week's stat lines)."""
    lines = league.query_rows("SELECT save_id, stats_json FROM player_game_stats WHERE week_num = ?", (week,))
    if not lines:
        return {}
    awards = {}
    for a in league.query_awards(week):
        awards[a['player_id']] = "conference" if a['award_type'].endswith("_Conf") and awards.get(a['player_id']) != "national" else "national"
    standout = tuning['game']['standout']
    results = {}
    for row in lines:
        stats = json.loads(row['stats_json'])
        results[row['save_id']] = {"played": (stats.get('DOWNSPLAYED') or 0) > 0,
                                   "standout": any((stats.get(k) or 0) >= v for k, v in standout.items()),
                                   "award": awards.get(row['save_id'])}
    return results

def load_players():
    tuning = load_tuning()
    stored = {r['save_id']: r for r in league.query_rows("SELECT * FROM care_players")}
    warnings = {}
    for w in league.query_rows("SELECT * FROM care_warnings WHERE open = 1 ORDER BY warning_id"):
        warnings.setdefault(w['save_id'], []).append({"id": w['warning_id'], "need": w['need'], "text": w['text']})
    players = roster_players()
    for p in players:
        row = stored.get(p['save_id'])
        p['needs'] = json.loads(row['needs_json']) if row else start_needs(p['save_id'], tuning)
        p['trust'] = row['trust'] if row else tuning['start_trust']
        p['change'] = json.loads(row['change_json']) if row and row['change_json'] else None
        p['warnings'] = warnings.get(p['save_id'], [])
    return players

def save_players(players, week):
    conn = database.get_db_connection()
    conn.executemany("INSERT OR REPLACE INTO care_players (save_id, needs_json, trust, change_json) VALUES (?, ?, ?, ?)",
                     [(p['save_id'], json.dumps(p['needs']), p['trust'], json.dumps(p['change']) if p.get('change') else None) for p in players])
    ids = {p['save_id'] for p in players}
    # Warnings a player no longer carries (a sit-down cleared them) are closed
    known = [w['id'] for p in players for w in p['warnings'] if 'id' in w]
    if known:
        conn.execute(f"UPDATE care_warnings SET open = 0 WHERE open = 1 AND warning_id NOT IN ({','.join('?' * len(known))})", known)
    else:
        conn.execute("UPDATE care_warnings SET open = 0 WHERE open = 1")
    conn.executemany("INSERT INTO care_warnings (week, save_id, need, text) VALUES (?, ?, ?, ?)",
                     [(week, p['save_id'], w['need'], w['text']) for p in players for w in p['warnings'] if 'id' not in w and p['save_id'] in ids])
    conn.commit()
    conn.close()

def council_ids():
    return [r['save_id'] for r in league.query_rows("SELECT save_id FROM care_council")]

def mentor_map():
    return {r['mentee']: r['mentor'] for r in league.query_rows("SELECT * FROM care_mentors")}

def season_seed():
    phase = json.loads(save_sync.get_state('phase') or "{}")
    return phase.get('seasonYear') or 0

def advance(week):
    """Runs every week from the last one played through `week` (called after each sync). The first call only
    sets up the roster at full-ish needs."""
    if week is None:
        return
    tuning = load_tuning()
    last = get_state("week")
    if last is None:
        players = load_players()
        save_players(players, week)
        set_state("week", week)
        set_state("hours", tuning['hours'])
        log(week, None, "start", f"Player care starts in Week {week}: every player begins with needs around {tuning['start_need']}.")
        return
    import care_incidents, care_messages
    last = int(last)
    # Arrows show everything since the coach last looked, even when a sync covers two weeks (a bye week): the
    # game's lift happens in the first of them and would vanish if only the last week counted
    start = {p['save_id']: dict(p['needs']) for p in load_players()}
    for w in range(last + 1, week + 1):
        players = load_players()
        ctx = week_context(w)
        seed = season_seed()
        rng = lambda key, w=w: random.Random(f"{seed}-{w}-{key}")
        games = game_results(w - 1, tuning)
        for p in players:
            p['game'] = games.get(p['save_id'], {"played": False, "standout": False, "award": None}) if games else None
        events = care_messages.close_week(players, w, tuning)   # texts left on read
        events += care_incidents.close_week(players, w, tuning)   # incidents nobody answered
        events += run_week(players, ctx, tuning, council_ids(), mentor_map(), rng)
        # Texts, emails and incidents only arrive in the week the coach will actually see: one made in a week the
        # sync skips past would expire, and count against him, before he could answer it
        seen = w == week
        if seen:
            events += care_incidents.roll(players, w, ctx, tuning, rng)
        for save_id, kind, text in events:
            log(w, save_id, kind, text)
        for p in players:   # what the update did to each need, before the coach steps in ("Morale 31, down 8")
            before = start.get(p['save_id'], p['needs'])
            p['change'] = {n: round(p['needs'][n] - before[n]) for n in NEEDS}
        if seen:
            care_messages.new_week(players, w, ctx, tuning, rng)
        save_players(players, w)
        set_state("week", w)
        set_state("hours", tuning['hours'])

# ---------- What the coach does ----------

def act(save_id, action_key, need, captain_id=None):
    tuning = load_tuning()
    week = int(get_state("week") or 0)
    hours = int(float(get_state("hours") or 0))
    action = tuning['actions'].get(action_key)
    if not action:
        raise ValueError("Unknown care action.")
    if action['hours'] > hours:
        raise ValueError(f"Not enough coach hours left this week ({hours} left, {action['label']} takes {action['hours']}).")
    players = load_players()
    by_id = {p['save_id']: p for p in players}
    player = by_id.get(save_id)
    if not player:
        raise ValueError("That player isn't on the roster.")
    captain = None
    if action_key == "council":
        captain = by_id.get(captain_id) if captain_id in council_ids() else next((by_id[c] for c in council_ids() if c in by_id and c != save_id), None)
        if not captain or captain['save_id'] == save_id:
            raise ValueError("Name a leadership council first: a captain handles this one.")
    text = apply_action(player, action_key, need, tuning, week_context(week), captain)
    save_players(players, week)
    set_state("hours", hours - action['hours'])
    log(week, save_id, "action", text)
    return dashboard()

def set_council(save_id, on):
    tuning = load_tuning()
    current = council_ids()
    if on and save_id not in current and len(current) >= tuning['council']['max']:
        raise ValueError(f"The leadership council holds {tuning['council']['max']} players.")
    conn = database.get_db_connection()
    if on:
        conn.execute("INSERT OR IGNORE INTO care_council (save_id) VALUES (?)", (save_id,))
    else:
        conn.execute("DELETE FROM care_council WHERE save_id = ?", (save_id,))
    conn.commit()
    conn.close()
    return dashboard()

def set_mentor(mentee, mentor):
    if mentor and mentor == mentee:
        raise ValueError("A player can't mentor themselves.")
    conn = database.get_db_connection()
    if mentor:
        conn.execute("INSERT OR REPLACE INTO care_mentors (mentee, mentor) VALUES (?, ?)", (mentee, mentor))
    else:
        conn.execute("DELETE FROM care_mentors WHERE mentee = ?", (mentee,))
    conn.commit()
    conn.close()
    return dashboard()

def set_preset(name):
    tuning = load_tuning()
    if name not in tuning['presets']:
        raise ValueError("Unknown difficulty.")
    set_state("preset", name)
    return dashboard()

# ---------- Simulator ----------

def simulate(weeks=12, policy="care", preset=None):
    """Plays `weeks` fake weeks of the care rules on a copy of the roster (nothing is saved). policy 'ignore' never
    acts; 'care' spends every hour each week on the care list the way a coach would: a sit-down for a warning sign,
    a call for a need that is low or slipping, a text for the rest."""
    tuning = load_tuning()
    if preset:
        tuning = {**tuning, **tuning['presets'][preset], "preset": preset}
    players = [{**p, "needs": start_needs(p['save_id'], tuning), "trust": tuning['start_trust'], "warnings": []} for p in roster_players()]
    council = [p['save_id'] for p in sorted(players, key=lambda p: (p['class'] != "Senior", -p['overall']))[:2]] if policy == "care" else []
    rng_seed = random.Random(7)
    import care_incidents
    warnings = low_weeks = incidents = 0
    cared_for = set()
    for w in range(1, weeks + 1):
        ctx = {"week": w, "exam": w in tuning['calendar']['exam_weeks'], "away": w % 2 == 0, "week_of_year": (35 + w) % 52}
        ctx['won'] = rng_seed.random() < 0.6
        ctx['lost'] = not ctx['won']
        ctx['big_win'] = ctx['won'] and rng_seed.random() < 0.2
        ctx['holiday'] = w == 12
        for p in players:   # a made-up game: starters and some backups play, a few have a standout day
            game_rng = random.Random(f"sim-game-{w}-{p['save_id']}")
            played = p['starter'] or game_rng.random() < 0.4
            p['game'] = {"played": played, "standout": played and game_rng.random() < 0.12, "award": None}
        care_list = pick_care_list(players, ctx, tuning, council)
        events = run_week(players, ctx, tuning, council, {}, lambda key, w=w: random.Random(f"sim-{w}-{key}"))
        warnings += sum(1 for _, kind, _ in events if kind == "warning")
        none = 1.0
        for p in players:
            none *= 1 - care_incidents.incident_chance(p, ctx, tuning)
        incidents += 1 - none   # the chance of an incident this week (at most one a week): adds up to the expected count
        low_weeks += sum(1 for p in players if min(p['needs'].values()) < tuning['low_need'])
        if policy == "care":
            hours = tuning['hours']
            for save_id in care_list:
                p = next(x for x in players if x['save_id'] == save_id)
                lowest = min(p['needs'].values())
                key = "sit_down" if p['warnings'] else "call" if lowest < tuning['low_need'] + tuning['sim_slipping_margin'] else "text"
                cost = tuning['actions'][key]['hours']
                if cost > hours:
                    key, cost = "text", tuning['actions']['text']['hours']
                if cost > hours:
                    break
                apply_action(p, key, min(NEEDS, key=lambda n: p['needs'][n]), tuning, ctx)
                hours -= cost
                cared_for.add(save_id)
    lows = [p for p in players if min(p['needs'].values()) < tuning['low_need']]
    return {"preset": tuning['preset'], "policy": policy, "weeks": weeks, "warning_signs": warnings, "incidents_expected": round(incidents, 1), "player_weeks_with_a_low_need": low_weeks,
            "players_with_a_low_need": len(lows), "average_need": round(sum(sum(p['needs'].values()) / len(NEEDS) for p in players) / len(players), 1),
            "average_trust": round(sum(p['trust'] for p in players) / len(players), 1),
            "players_cared_for": len(cared_for),
            "trust_of_players_cared_for": round(sum(p['trust'] for p in players if p['save_id'] in cared_for) / len(cared_for), 1) if cared_for else None}

# ---------- Page ----------

def current_week():
    """The week of our next game (what the coach is preparing for)."""
    game = database.query_active_week()
    return game['week_id'] if game else None

def dashboard():
    import care_incidents, care_messages
    tuning = load_tuning()
    if get_state("week") is None:
        advance(current_week())  # first look: set the roster up
    week = get_state("week")
    if week is None:
        return {"started": False}
    week = int(week)
    players = load_players()
    by_id = {p['save_id']: p for p in players}
    ctx = week_context(week)
    council = council_ids()
    mentors = mentor_map()
    # Everyone, most urgent first, split into who needs the coach now, who is slipping, and everyone else
    ranked = pick_care_list(players, ctx, {**tuning, "care_list_size": len(players)}, council)
    def group(p):
        lowest = min(p['needs'].values())
        return "now" if p['warnings'] or lowest < tuning['low_need'] else "close" if lowest < tuning['watch_need'] else "fine"
    games = game_results(week - 1, tuning)
    def view(p):
        flags = []
        game = games.get(p['save_id'])
        if game and game['award']:
            flags.append("Player of the Week" if game['award'] == "national" else "Conference Player of the Week")
        elif game and game['standout']:
            flags.append("Standout game")
        if p['save_id'] in council:
            flags.append("Captain")
        if p['birthday_week'] == ctx.get('week_of_year'):
            flags.append("Birthday this week")
        if p['distance'] and p['needs']['home'] < tuning['homesick_below']:
            flags.append("Homesick")
        flags += [t for t in p['traits'] if t in ("Disciplined", "Undisciplined")]
        if p['injured']:
            flags.append("Injured")
        if p['hot_cold'] in ("Hot", "Cold"):
            flags.append(f"Starts {p['hot_cold']}")
        mentor = by_id.get(mentors.get(p['save_id']))
        return {"save_id": p['save_id'], "name": p['name'], "position": p['position'], "class": p['class'], "overall": p['overall'],
                "portrait": p['portrait'], "needs": {n: round(p['needs'][n]) for n in NEEDS}, "trust": p['trust'], "flags": flags,
                "warnings": [w['text'] for w in p['warnings']], "mentor": mentor['name'] if mentor else None,
                "lowest": min(NEEDS, key=lambda n: p['needs'][n]), "change": p['change']}
    calendar = [label for key, label in (("exam", "Exam week: academics drain faster"), ("holiday", "Holiday week: players far from home miss it"),
                                          ("senior_day", "Senior day this week"), ("big_win", "Big win last week: focus slips")) if ctx.get(key)]
    suggestions = [p['save_id'] for p in sorted(players, key=lambda p: ({"Senior": 0, "Junior": 1}.get(p['class'], 2), -p['overall']))[:6]]
    return {
        "started": True, "week": week, "hours": int(float(get_state("hours") or 0)), "hours_total": tuning['hours'],
        "preset": tuning['preset'], "presets": list(tuning['presets']), "calendar": calendar,
        "low_need": tuning['low_need'], "watch_need": tuning['watch_need'],
        "needs": [{"key": n, "label": NEED_LABELS[n]} for n in NEEDS],
        "actions": [{"key": k, "label": a['label'], "hours": a['hours'], "fill": a['fill'], "fills": a.get('fills'),
                     "clears_warnings": bool(a.get('clears_warnings'))} for k, a in tuning['actions'].items()],
        "groups": {name: [view(by_id[s]) for s in ranked if group(by_id[s]) == name] for name in ("now", "close", "fine")},
        "council": [view(by_id[s]) for s in council if s in by_id], "council_max": tuning['council']['max'],
        "council_suggestions": [s for s in suggestions if s not in council][:4],
        "mentors": [{"mentee": view(by_id[m]), "mentor": view(by_id[t])} for m, t in mentors.items() if m in by_id and t in by_id],
        "roster": sorted(({"save_id": p['save_id'], "name": p['name'], "position": p['position'], "class": p['class']} for p in players),
                         key=lambda p: (p['position'], p['name'])),
        "log": league.query_rows("SELECT week, kind, text FROM care_log ORDER BY log_id DESC LIMIT 40"),
        "phone": care_messages.phone_view(week, by_id), "inbox": care_messages.inbox_view(),
        "incidents": care_incidents.open_incidents(tuning),
        "unread": {**dict(zip(("texts", "emails"), care_messages.unread())), "incidents": care_messages.open_incident_count()},
    }

# ---------- Campus feed mood ring ----------

# How campus chatter would notice each empty need: outward signs only, never a reason or a rumor
MOOD_SIGNS = {"morale": "seems down lately", "academics": "has looked stressed and buried in the books",
              "home": "seems a little homesick", "focus": "seems off and distracted lately", "health": "looks worn down"}

def mood_hints(limit=2):
    """Up to `limit` players for the campus feed to hint about: the most worrying low need first, then one player
    riding high (a top morale or an award). Returns [(player, sign)]; empty before care starts."""
    if get_state("week") is None:
        return []
    tuning = load_tuning()
    players = [p for p in load_players() if p['starter'] or p['dev'] in ("Impact", "Star", "Elite")]  # players fans would notice
    hints = []
    worried = sorted((p for p in players if min(p['needs'].values()) < tuning['watch_need']), key=lambda p: min(p['needs'].values()))
    for p in worried[:max(1, limit - 1)]:   # leave room for someone riding high
        hints.append((p, MOOD_SIGNS[min(NEEDS, key=lambda n: p['needs'][n])]))
    games = game_results(int(get_state("week")) - 1, tuning)
    high = sorted((p for p in players if p not in worried and (p['needs']['morale'] >= 85 or (games.get(p['save_id']) or {}).get('award'))),
                  key=lambda p: -p['needs']['morale'])
    if high and len(hints) < limit:
        hints.append((high[0], "is all smiles and riding high"))
    return hints[:limit]

def mood_context():
    """A plan line for the hub generator's campus feed, or "" when nobody stands out."""
    hints = mood_hints()
    if not hints:
        return ""
    lines = "; ".join(f"{p['name']} ({p['position']}) {sign}" for p, sign in hints)
    return (f"Campus mood (what people around the team have noticed off the field): {lines}. "
            "Keep it to light, vague chatter about how he seems: no rumors, no reasons, no trouble, no injuries.")

initialize_care_tables()
