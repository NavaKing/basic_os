import json
import random
import re
import database
import roster
import ai_engine
import team
import progress

MAX_ACTIVE_STORYLINES = 4

# Shared rules appended to every storyline prompt
WRITING_RULES = "The players are on a men's college football team; refer to each player as he/him. Refer to players by name and position (e.g. 'wide receiver'), never depth chart codes like WR1 or QB2. Yardage in the season context is the whole team's total, never one player's stats. Never invent games, plays, scores or stats that aren't given here; write about the decision, practice and the locker room instead. Do not output raw code strings or brackets."

# Premise templates the AI builds each storyline from. {rival_clause} is filled in when a rival exists.
STORYLINE_PREMISES = {
    "hype": "{player} is riding a wave of hype after strong play and has no intention of giving up the starting job{rival_clause}.",
    "pressure": "{player} is under fire from fans and media after shaky play, and the starting job is suddenly in question{rival_clause}.",
    "battle": "{player} is making a serious push to take the spot of {rival} on the depth chart.",
    "comeback": "{player} is fighting back from a {injury} and wants to prove nothing has changed{rival_clause}.",
    "recruit": "{player} is feeling the heat now that a highly rated recruit at his position has committed to the program{rival_clause}."
}

# Thresholds for spotting storylines in a game's stats (see impact_score)
STANDOUT_IMPACT = 25      # a performance worth a storyline
BATTLE_MARGIN = 5         # how clearly a backup must outplay the player ahead of him
PRESSURE_TURNOVERS = 2    # interceptions + fumbles that put a starter under pressure

def initialize_storyline_tables():
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS storylines (
        storyline_id INTEGER PRIMARY KEY AUTOINCREMENT,
        storyline_type TEXT NOT NULL,
        title TEXT NOT NULL,
        premise TEXT NOT NULL,
        player_id INTEGER NOT NULL,
        rival_id INTEGER,
        player_slot TEXT, -- depth slots when the storyline started, used to detect depth chart changes
        rival_slot TEXT,
        status TEXT DEFAULT 'active', -- 'active' or 'resolved'
        start_week INTEGER NOT NULL,
        end_week INTEGER,
        resolution TEXT,
        finale_text TEXT,
        source_week INTEGER, -- the game that sparked it (NULL for random storylines)
        trigger_text TEXT    -- the stat lines that sparked it
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS storyline_chapters (
        chapter_id INTEGER PRIMARY KEY AUTOINCREMENT,
        storyline_id INTEGER NOT NULL,
        week_num INTEGER NOT NULL,
        chapter_text TEXT NOT NULL,
        UNIQUE(storyline_id, week_num)
    )
    """)
    # Add the game-trigger columns to tables created before they existed
    existing_cols = [col[1] for col in cursor.execute("PRAGMA table_info(storylines)").fetchall()]
    for col, col_type in (("source_week", "INTEGER"), ("trigger_text", "TEXT")):
        if col not in existing_cols:
            cursor.execute(f"ALTER TABLE storylines ADD COLUMN {col} {col_type}")
    conn.commit()
    conn.close()

def split_slot(slot):
    """'WR2' -> ('WR', 2)"""
    match = re.match(r"([A-Z]+)(\d+)$", slot or "")
    return (match.group(1), int(match.group(2))) if match else (None, None)

def query_storyline_rows(status):
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM storylines WHERE status = ? ORDER BY storyline_id DESC LIMIT 20", (status,))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

def query_chapters(storyline_id):
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM storyline_chapters WHERE storyline_id = ? ORDER BY week_num ASC", (storyline_id,))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

def latest_stat_line(player):
    """(week, '18 car, 135 rush yds') from the most recent played game, or (None, '') if no stats."""
    last_played = database.query_last_played_week()
    if not player or not player.get('save_id') or not last_played:
        return None, ""
    stats = roster.query_player_week_stats(player['save_id'], last_played['week_id'])
    return last_played['week_id'], roster.format_stat_line(stats)

def cast_member(player, role):
    if not player:
        return {"role": role, "name": "Former player", "position": "", "slot": "", "jersey": None,
                "health_status": "", "stat_week": None, "stat_line": ""}
    stat_week, stat_line = latest_stat_line(player)
    return {
        "role": role,
        "name": player['player_name'],
        "position": player['position'],
        "slot": player['depth_slot'],
        "jersey": player['jersey_num'],
        "health_status": player['health_status'],
        "stat_week": stat_week,
        "stat_line": stat_line
    }

def query_storylines():
    """Active and recently resolved storylines, ready for the page."""
    result = {}
    for status in ("active", "resolved"):
        result[status] = []
        for s in query_storyline_rows(status):
            player = roster.query_player(s['player_id'])
            rival = roster.query_player(s['rival_id']) if s['rival_id'] else None
            s['cast'] = [cast_member(player, "Focus")]
            if s['rival_id']:
                s['cast'].append(cast_member(rival, "Rival"))
            # The depth chart button promotes whichever of the two is lower on the chart
            s['depth_action_label'] = None
            if player and rival:
                backup = player if split_slot(player['depth_slot'])[1] > split_slot(rival['depth_slot'])[1] else rival
                s['depth_action_label'] = f"Promote {backup['player_name']}"
            s['chapters'] = query_chapters(s['storyline_id'])
            result[status].append(s)
    return result

def busy_player_ids():
    busy = set()
    for s in query_storyline_rows("active"):
        busy.update([s['player_id'], s['rival_id']])
    return busy

def find_storyline_candidates():
    """Every (type, player, rival) combination the current roster and depth chart can support."""
    players = [p for p in roster.query_full_roster() if split_slot(p['depth_slot'])[0]]
    busy = busy_player_ids()
    by_slot = {p['depth_slot']: p for p in players if p['player_id'] not in busy}

    candidates = []
    for p in players:
        if p['player_id'] in busy:
            continue
        pos, rank = split_slot(p['depth_slot'])
        injured = p['health_status'] in ('Questionable', 'Doubtful', 'Out')
        next_up = by_slot.get(f"{pos}{rank + 1}")
        if rank == 1 and not injured:
            candidates.append(("hype", p, next_up))
            candidates.append(("pressure", p, next_up))
        if rank == 2 and by_slot.get(f"{pos}1"):
            candidates.append(("battle", p, by_slot[f"{pos}1"]))
        if injured and p['duration_weeks'] != 'Season':
            candidates.append(("comeback", p, next_up))
    return candidates

def impact_score(stats):
    """How much a player stood out in a game. Uses the game's own rating (offense) or a tackle/turnover score (defense)."""
    if not stats:
        return 0
    s = lambda key: stats.get(key, 0)
    defense = (2 * s('DEFTACKLES') + s('ASSDEFTACKLES') + 4 * s('DEFPASSDEFLECTIONS') + 15 * s('DSECINTS')
               + 10 * s('DLINESACKS') + 5 * s('DLINEHALFSACK') + 8 * s('DLINEFORCEDFUMBLES') + 8 * s('DLINEFUMBLERECOVERIES'))
    return max(s('GAMERATING'), defense)

def turnovers(stats):
    """Interceptions thrown plus fumbles (the save records fumbles by any ball carrier as RUSHFUMBLES)."""
    return sum((stats or {}).get(key, 0) for key in ('PASSINTS', 'RUSHFUMBLES'))

def find_game_events(week):
    """Storyline-worthy moments from a played game, best first: [(type, player, rival, trigger_text, trigger_prose)]."""
    stats = roster.query_week_stats(week)
    players = [p for p in roster.query_full_roster() if p['save_id'] and split_slot(p['depth_slot'])[0]]
    rank_of = lambda p: split_slot(p['depth_slot'])[1]
    by_position = {}
    for p in players:
        by_position.setdefault(p['position'], []).append(p)
    for group in by_position.values():
        group.sort(key=rank_of)
    # Compact text for the page, plain English for the AI (it copies codes like 'HB2' and 'tkl' into its writing)
    stat_text = lambda p: f"{p['player_name']} ({p['depth_slot']}): {roster.format_stat_line(stats.get(p['save_id'])) or 'no stats'}"
    stat_prose = lambda p: f"{roster.describe_player(p)} had {roster.format_stat_line(stats.get(p['save_id']), 'prose') or 'no stats'}"

    events = []  # (priority, type, player, rival, trigger)
    for position, group in by_position.items():
        for p in group:
            p_stats = stats.get(p['save_id'])
            score = impact_score(p_stats)
            # Battle: a backup clearly outplayed someone ahead of him who also made plays
            if rank_of(p) > 1 and score >= STANDOUT_IMPACT:
                ahead = [q for q in group if rank_of(q) < rank_of(p) and roster.format_stat_line(stats.get(q['save_id']))]
                if ahead:
                    rival = min(ahead, key=lambda q: (impact_score(stats[q['save_id']]), -rank_of(q)))
                    if score >= impact_score(stats[rival['save_id']]) + BATTLE_MARGIN:
                        events.append((300 + score, "battle", p, rival, f"{stat_text(p)} vs {stat_text(rival)}", f"{stat_prose(p)}, while {stat_prose(rival)}"))
            if rank_of(p) != 1 or not p_stats:
                continue
            next_up = group[1] if len(group) > 1 else None
            # Pressure: a starter turned the ball over repeatedly
            if turnovers(p_stats) >= PRESSURE_TURNOVERS:
                events.append((200 + 10 * turnovers(p_stats), "pressure", p, next_up, stat_text(p), stat_prose(p)))
            # Hype: a starter had a standout game
            elif score >= STANDOUT_IMPACT:
                events.append((100 + score, "hype", p, next_up, stat_text(p), stat_prose(p)))
    # Comeback: anyone currently injured (short of season-ending)
    for p in players:
        if p['health_status'] in ('Questionable', 'Doubtful', 'Out') and p['duration_weeks'] != 'Season':
            group = by_position[p['position']]
            next_up = next((q for q in group if rank_of(q) == rank_of(p) + 1), None)
            events.append((50, "comeback", p, next_up, f"{p['player_name']} ({p['depth_slot']}): {p['injury_type']}, {p['duration_weeks']}",
                           f"{roster.describe_player(p)} is injured ({p['injury_type'].lower()}, expected out {p['duration_weeks'].lower()})"))

    events.sort(key=lambda e: -e[0])
    return [e[1:] for e in events]

def build_premise(storyline_type, player, rival):
    rival_clause = f", with {roster.describe_player(rival)} waiting in the wings" if rival else ""
    return STORYLINE_PREMISES[storyline_type].format(
        player=roster.describe_player(player),
        rival=roster.describe_player(rival) if rival else "",
        injury=player['injury_type'].lower(),
        rival_clause=rival_clause
    )

def team_name():
    return team.user_team()['name']

def season_context():
    active_week = database.query_active_week()
    prev_context = ai_engine.build_prev_context(database.query_last_played_week())
    return active_week, f"{prev_context} {team_name()}'s next game is Week {active_week['week_id']} vs {active_week['opponent_name']}."

def start_storyline(storyline_type, player, rival, selected_model, source_week=None, trigger_text=None, trigger_prose=None):
    premise = build_premise(storyline_type, player, rival)
    active_week, context = season_context()
    if trigger_prose and source_week:
        trigger = f" What sparked it, from the Week {source_week} game (these are the individual players' own stats): {trigger_prose}."
    else:
        trigger = f" What sparked it: {trigger_prose}." if trigger_prose else ""

    prompt = f'You are a beat writer covering {team_name()} Football. Start a new player storyline that will play out over several weeks. Premise: {premise}{trigger} Season context: {context} {WRITING_RULES} Respond with ONLY a JSON object in exactly this shape: {{"title": "short punchy headline", "intro": "2-3 sentence opening chapter"}}'
    data = json.loads(ai_engine.call_ollama(selected_model, prompt, force_json=True))
    if not isinstance(data, dict) or not data.get('intro'):
        raise ValueError("The model didn't return a usable storyline. Try again.")

    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO storylines (storyline_type, title, premise, player_id, rival_id, player_slot, rival_slot, start_week, source_week, trigger_text)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (storyline_type, data.get('title') or premise, premise, player['player_id'],
          rival['player_id'] if rival else None, player['depth_slot'], rival['depth_slot'] if rival else None,
          active_week['week_id'], source_week, trigger_text))
    cursor.execute("INSERT INTO storyline_chapters (storyline_id, week_num, chapter_text) VALUES (?, ?, ?)",
                   (cursor.lastrowid, active_week['week_id'], data['intro']))
    conn.commit()
    conn.close()

def create_storyline(selected_model):
    """Starts one storyline from a random eligible player."""
    if len(query_storyline_rows("active")) >= MAX_ACTIVE_STORYLINES:
        raise ValueError(f"Already {MAX_ACTIVE_STORYLINES} active storylines. End one before starting another.")
    candidates = find_storyline_candidates()
    if not candidates:
        raise ValueError("No eligible players for a new storyline. Every depth chart player is already in one.")
    storyline_type, player, rival = random.choice(candidates)
    start_storyline(storyline_type, player, rival, selected_model)

def create_storylines_from_game(selected_model):
    """Starts storylines from the standout moments of the most recent played game. Returns how many were created."""
    last_played = database.query_last_played_week()
    if not last_played:
        raise ValueError("No games have been played yet.")
    open_slots = MAX_ACTIVE_STORYLINES - len(query_storyline_rows("active"))
    if open_slots <= 0:
        raise ValueError(f"Already {MAX_ACTIVE_STORYLINES} active storylines. End one before starting another.")

    used = busy_player_ids()
    created = 0
    for storyline_type, player, rival, trigger_text, trigger_prose in find_game_events(last_played['week_id']):
        if created >= open_slots:
            break
        if player['player_id'] in used or (rival and rival['player_id'] in used):
            continue
        start_storyline(storyline_type, player, rival, selected_model, last_played['week_id'], trigger_text, trigger_prose)
        used.update([player['player_id'], rival['player_id'] if rival else None])
        created += 1
    if not created:
        raise ValueError(f"No new storylines from Week {last_played['week_id']}: every standout performance already has one.")
    return created

def advance_storylines(selected_model):
    """Writes this week's chapter for every active storyline that doesn't have one yet."""
    active_week, context = season_context()
    for s in query_storyline_rows("active"):
        chapters = query_chapters(s['storyline_id'])
        if any(c['week_num'] == active_week['week_id'] for c in chapters):
            continue
        progress.step("Writing storyline chapters", s['title'])
        story_so_far = " ".join(f"Week {c['week_num']}: {c['chapter_text']}" for c in chapters[-2:])
        # Ground the chapter in how the cast actually played last game
        cast_stats = []
        last_played = database.query_last_played_week()
        for player_id in (s['player_id'], s['rival_id']):
            player = roster.query_player(player_id) if player_id else None
            stats = roster.query_player_week_stats(player['save_id'], last_played['week_id']) if player and player.get('save_id') and last_played else None
            if stats and roster.format_stat_line(stats):
                cast_stats.append(f"{roster.describe_player(player)} in Week {last_played['week_id']}: {roster.format_stat_line(stats, 'prose')}")
        latest_game = f" Latest individual stats: {'; '.join(cast_stats)}." if cast_stats else ""
        prompt = f"You are a beat writer covering {team_name()} Football. Continue this ongoing player storyline titled \"{s['title']}\". Premise: {s['premise']} Story so far: {story_so_far}{latest_game} Season context: {context} Write the 2-sentence chapter for Week {active_week['week_id']}. Move the story forward, but do not resolve it: only the head coach decides how it ends. {WRITING_RULES}"
        try:
            chapter_text = ai_engine.call_ollama(selected_model, prompt)
        except Exception:
            continue  # Try again on the next hub generation
        conn = database.get_db_connection()
        conn.execute("INSERT OR REPLACE INTO storyline_chapters (storyline_id, week_num, chapter_text) VALUES (?, ?, ?)",
                     (s['storyline_id'], active_week['week_id'], chapter_text))
        conn.commit()
        conn.close()

def build_player_impact_lines(limit=4):
    """Plain-English stat lines for the players who most shaped the last game (biggest impact, plus any turnover-prone starter)."""
    last_played = database.query_last_played_week()
    if not last_played:
        return []
    stats = roster.query_week_stats(last_played['week_id'])
    players = [p for p in roster.query_full_roster() if p['save_id'] in stats and roster.format_stat_line(stats[p['save_id']])]
    standouts = sorted(players, key=lambda p: -impact_score(stats[p['save_id']]))[:limit]
    standouts += [p for p in players if turnovers(stats[p['save_id']]) >= PRESSURE_TURNOVERS and p not in standouts]
    # "(he/him)" next to each name: the model otherwise guesses pronouns from first names
    return [f"{roster.describe_player(p)} (he/him), who had {roster.format_stat_line(stats[p['save_id']], 'prose')}" for p in standouts]

def build_storyline_titles():
    """Just the storyline headlines, for prompts where full chapters would crowd out everything else."""
    return "; ".join(f"\"{s['title']}\"" for s in query_storyline_rows("active"))

def build_storyline_context():
    """One line per active storyline (title and latest chapter) for the weekly article and tweet prompts."""
    lines = []
    for s in query_storyline_rows("active"):
        chapters = query_chapters(s['storyline_id'])
        latest = chapters[-1]['chapter_text'] if chapters else ""
        lines.append(f"\"{s['title']}\": {latest}")
    return " | ".join(lines)

def mark_resolved(storyline_id, resolution, finale_text):
    conn = database.get_db_connection()
    conn.execute("UPDATE storylines SET status = 'resolved', end_week = ?, resolution = ?, finale_text = ? WHERE storyline_id = ?",
                 (database.query_active_week()['week_id'], resolution, finale_text, storyline_id))
    conn.commit()
    conn.close()

def resolve_storyline(storyline_id, action, selected_model):
    """Ends a storyline by the coach's decision: 'depth_change' swaps the two players, 'end' keeps the depth chart as is."""
    s = next((row for row in query_storyline_rows("active") if row['storyline_id'] == storyline_id), None)
    if not s:
        raise ValueError("That storyline is no longer active.")
    player = roster.query_player(s['player_id'])
    rival = roster.query_player(s['rival_id']) if s['rival_id'] else None

    if action == "depth_change":
        if not rival:
            raise ValueError("This storyline has no second player to swap on the depth chart.")
        roster.swap_depth_slots(player['player_id'], rival['player_id'])
        decision = f"The head coach changed the depth chart: {player['player_name']} moves from {player['depth_slot']} to {rival['depth_slot']}, and {rival['player_name']} moves to {player['depth_slot']}."
    elif action == "end":
        decision = f"The head coach made no depth chart change: {player['player_name']} stays at {player['depth_slot']}"
        decision += f" and {rival['player_name']} stays at {rival['depth_slot']}." if rival else "."
    else:
        raise ValueError(f"Unknown action: {action}")

    chapters = query_chapters(storyline_id)
    story_so_far = " ".join(f"Week {c['week_num']}: {c['chapter_text']}" for c in chapters[-2:])
    prompt = f"You are a beat writer covering {team_name()} Football. Write the 2-sentence final chapter of the player storyline titled \"{s['title']}\". Premise: {s['premise']} Story so far: {story_so_far} How it ends: {decision} This chapter happens this week, before the next game is played: describe the coach's decision and how the two players and the locker room react to it. {WRITING_RULES}"
    try:
        finale_text = ai_engine.call_ollama(selected_model, prompt)
    except Exception:
        finale_text = None  # Still end the storyline; the page shows the decision instead
    mark_resolved(storyline_id, decision, finale_text)

def check_depth_changes():
    """Ends any active storyline whose players were moved on the depth chart outside the storyline buttons."""
    for s in query_storyline_rows("active"):
        player = roster.query_player(s['player_id'])
        rival = roster.query_player(s['rival_id']) if s['rival_id'] else None
        if not player or (s['rival_id'] and not rival):
            mark_resolved(s['storyline_id'], "A player in this storyline is no longer on the roster.", None)
            continue
        player_moved = player and player['depth_slot'] != s['player_slot']
        rival_moved = rival and rival['depth_slot'] != s['rival_slot']
        if player_moved or rival_moved:
            moves = [f"{p['player_name']} is now {p['depth_slot']}" for p, moved in ((player, player_moved), (rival, rival_moved)) if moved]
            mark_resolved(s['storyline_id'], "Depth chart change: " + ", ".join(moves) + ".", None)

# Auto-initialize when storylines.py gets imported by app.py
initialize_storyline_tables()
