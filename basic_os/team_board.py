"""Team Board: an internal, players-only feed in the Locker Room. About 20 posts a week by our own players about the
last game and how they're feeling, with teammates replying to each other. Separate from the public campus feed.

Each player's post is grounded in his real stat line from the last game and his player care mood. Guardrails, because
most players are real college athletes: football and team topics only (no off-field life, beefs or drama), no made-up
social handles, and numbers are checked against the facts given to the model."""
import difflib
import json
import random
import re
import care
import database
import fact_check
import media
import roster
import sentences
import storylines

POSTS = 12      # first pass: players posting
REPLIES = 8     # second pass: teammates replying to those posts
CAST_SIZE = 16
TEMPERATURE = 0.9

# Each week every poster gets an angle, so a player doesn't say the same thing every week ("177 yards felt good, thanks
# to the o-line" became "212 yards felt good, thanks to the o-line"). Players reacting to their stats get a STAT_ANGLE.
# How a player reacts to his numbers depends on how good they were: nobody calls a 212-yard game "not enough".
STAT_ANGLES = {
    "great": ["proud of a big game, and he knows it", "gives the credit for his big game to one teammate by name", "jokes about his big game"],
    "good": ["happy with a good game", "gives the credit for his numbers to one teammate by name", "jokes about his numbers"],
    "solid": ["a solid game, and he wants more", "gives the credit for his numbers to one teammate by name"],
    "rough": ["hard on himself after a rough game, owns it", "says he'll bounce back after a rough game"],
}

# One game's stat line against college football benchmarks: (stat, good, great). Hitting "great" on any line makes it a
# great game; turnovers pull it down. The words go into the prompt so the model knows what the numbers mean.
BENCHMARKS = [("RUSHYARDS", 100, 150), ("RECEIVEYARDS", 100, 150), ("PASSYARDS", 250, 350), ("RUSHTDS", 1, 2), ("RECEIVETDS", 1, 2),
              ("PASSTDS", 2, 3), ("DEFTACKLES", 8, 12), ("DLINESACKS", 1, 2), ("DSECINTS", 1, 2), ("DLINEFORCEDFUMBLES", 1, 2),
              ("KICKFGMADE", 2, 4)]
GRADE_WORDS = {"great": "a great game by college football standards", "good": "a good game", "solid": "a solid, ordinary game",
               "rough": "a rough game"}
ANGLES = ["shouts out one teammate by name for something specific", "talks about one play from the game", "looks ahead to the next opponent",
          "talks about practice or film this week", "something funny from the locker room or the bus ride", "how the crowd or the road trip felt",
          "a quick hype post", "his goal for this week"]
TOO_SIMILAR = 0.6   # a post this close to his previous one is dropped

GUARDRAILS = ("Every player is a man on a men's college football team, so always use he/him/his. This is the team's private, "
              "internal board, so posts are casual, like teammates texting a group chat: short, lowercase is fine, emojis are fine. "
              "Posts are only about football, the last game, practice, teammates, coaches and the next opponent. Never write about "
              "life off the field, relationships, parties, money, NIL deals, rumors, beefs, injuries the facts don't mention, or "
              "anything negative about a named teammate. Only use numbers from the facts. Each player's 'how he feels' note is private to "
              "him: only his own post may hint at it, and nobody ever mentions another player's mood, health, school or personal life.")

def initialize_tables():
    conn = database.get_db_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS team_board_posts (
        post_id INTEGER PRIMARY KEY AUTOINCREMENT,
        week INTEGER, save_id TEXT, text TEXT, reply_to INTEGER
    )
    """)
    conn.commit()
    conn.close()

def mood_words(p, tuning):
    """How a player is doing, in plain words for the prompt (from player care)."""
    needs = p['needs']
    lowest = min(care.NEEDS, key=lambda n: needs[n])
    if (p.get('game') or {}).get('award') == "national":
        return "on top of the world: he was just named Player of the Week"
    if needs['morale'] >= 80:
        return "feeling great and confident"
    if needs[lowest] < tuning['low_need']:
        return {"morale": "down and frustrated", "academics": "stressed, buried in schoolwork", "home": "homesick",
                "focus": "distracted, head not fully in it", "health": "worn down and sore"}[lowest]
    if needs[lowest] < tuning['watch_need']:
        return {"morale": "a little down", "academics": "busy with school", "home": "missing home a bit",
                "focus": "a little scattered", "health": "banged up"}[lowest]
    return "in a good place"

def cast(week):
    """Who posts: last game's biggest impact players first, then starters and anyone whose mood stands out."""
    tuning = care.load_tuning()
    players = care.load_players() if care.get_state("week") is not None else []
    games = care.game_results(week, tuning) if week else {}
    jerseys = {p['save_id']: p.get('jersey_num') for p in roster.query_full_roster()}
    out = []
    for p in players:
        stats = roster.query_player_week_stats(p['save_id'], week) if week else {}
        p['game'] = games.get(p['save_id'])
        mood = mood_words(p, tuning)
        out.append({"save_id": p['save_id'], "name": p['name'], "position": p['position'], "class": p['class'], "jersey": jerseys.get(p['save_id']),
                    "portrait": p['portrait'], "line": roster.format_stat_line(stats) if stats else "", "impact": impact(stats),
                    "grade": grade(stats) if stats and stats.get('DOWNSPLAYED') else None,
                    "starter": p['starter'], "played": bool(stats and stats.get('DOWNSPLAYED')), "mood": mood,
                    "stands_out": mood != "in a good place"})
    out.sort(key=lambda c: (-c['impact'], not c['stands_out'], not c['starter'], c['name']))
    picked = out[:CAST_SIZE - 4] + [c for c in out[CAST_SIZE - 4:] if c['stands_out'] or not c['played']][:4]  # a few bench and mood voices
    return picked

def impact(stats):
    """How much he stood out: the game's own rating or the defensive score, or yards and touchdowns (the save only rates some)."""
    s = lambda key: (stats or {}).get(key, 0)
    production = (s('RUSHYARDS') + s('RECEIVEYARDS')) / 10 + s('PASSYARDS') / 25 + 6 * (s('RUSHTDS') + s('RECEIVETDS') + s('PASSTDS'))
    return max(storylines.impact_score(stats), production)

def grade(stats):
    """'great', 'good', 'solid' or 'rough' for one game's stat line (None without one)."""
    if not stats:
        return None
    s = lambda key: stats.get(key, 0) or 0
    level = 1   # solid
    for stat, good, great in BENCHMARKS:
        if s(stat) >= great:
            level = max(level, 3)
        elif s(stat) >= good:
            level = max(level, 2)
    turnovers = s('PASSINTS') + s('RUSHFUMBLES')
    if turnovers >= 2:
        level -= 1
    if s('PASSATTEMPTS') >= 20 and s('PASSYARDS') < 150 and not s('PASSTDS'):
        level = min(level, 0)
    if s('RUSHATTEMPTS') >= 12 and s('RUSHYARDS') < 40:
        level = min(level, 0)
    return ["rough", "solid", "good", "great"][max(0, min(3, level))]

def assign_angles(people, week):
    """The players with the biggest stat lines react to them (each a different way); everyone else gets another angle."""
    rng = random.Random(f"board-{week}")
    angles = ANGLES[:]
    rng.shuffle(angles)
    stat_posters = [c for c in people if c['line']][:POSTS // 2]
    others = [c for c in people if c not in stat_posters]
    decks = {g: rng.sample(options, len(options)) for g, options in STAT_ANGLES.items()}   # rotate, so two good games react differently
    used = {g: 0 for g in STAT_ANGLES}
    for c in stat_posters:
        g = c['grade'] or "solid"
        c['angle'] = decks[g][used[g] % len(decks[g])]
        used[g] += 1
    for i, c in enumerate(others):
        c['angle'] = angles[i % len(angles)]

def previous_posts(week):
    """{save_id: his most recent post from an earlier week}."""
    conn = database.get_db_connection()
    rows = conn.execute("SELECT save_id, text FROM team_board_posts WHERE reply_to IS NULL AND week < ? ORDER BY week, post_id", (week or 0,)).fetchall()
    conn.close()
    return {r['save_id']: r['text'] for r in rows}

def describe(c):
    played = (f"last game: {c['line']}" + (f", {GRADE_WORDS[c['grade']]}" if c.get('grade') else "") if c['line']
              else ("played but had no stats" if c['played'] else "didn't play last game (bench)"))
    text = f"{c['name']} ({c['class']} {c['position']}{', #' + str(c['jersey']) if c['jersey'] else ''}; {played}; how he feels, for tone only: {c['mood']}"
    if c.get('angle'):
        text += f"; his post this week: {c['angle']}"
    if c.get('previous'):
        text += f"; his last post, never repeat it or reuse its wording: \"{c['previous']}\""
    return text + ")"

def game_facts():
    import ai_engine
    last = database.query_last_played_week()
    nxt = database.query_active_week()
    facts = [ai_engine.build_prev_context(last)] if last else []
    if nxt and not nxt['is_played']:
        facts.append(f"Next game: Week {nxt['week_id']} {'at' if nxt.get('site') == 'Away' else 'against'} {nxt['opponent_name']}.")
    return " ".join(facts)

def scrub(text, people):
    """Drops the prompt's mood notes when the model copies them into a post ('... in a good place 🤙'): a note
    tacked on the end is cut off, and a sentence built around one is dropped (cutting it out mid-sentence leaves nonsense)."""
    moods = {c['mood'] for c in people}
    for mood in moods:
        text = re.sub(r"[\s.,;:-]*" + re.escape(mood) + r"[.!]?(\s*\W*)$", r"\1", text, flags=re.IGNORECASE)
    kept = [s for s in sentences.split(text) if not any(m.lower() in s.lower() for m in moods)]
    return re.sub(r"\s{2,}", " ", " ".join(kept)).strip()

# The save never says how long a touchdown was, so "a 30 yard TD" / "that td for 37 yards" merges two stats into a claim
TD_LENGTH = re.compile(r"\d+[- ]?(?:yd|yard)s?\W*(?:td|touchdown|score)|(?:td|touchdown)\W+(?:for|of)\W+\d+", re.IGNORECASE)

def drop_td_lengths(text):
    return " ".join(s for s in sentences.split(text) if not TD_LENGTH.search(s))

def repeats(text, previous):
    return bool(previous) and difflib.SequenceMatcher(None, text.lower(), previous.lower()).ratio() >= TOO_SIMILAR

def parse(raw, names, key="posts"):
    data = json.loads(raw)
    items = data.get(key, []) if isinstance(data, dict) else data
    return [i for i in items if isinstance(i, dict) and i.get('author') in names and (i.get('text') or "").strip()]

def generate(selected_model):
    import ai_engine
    last = database.query_last_played_week()
    week = last['week_id'] if last else None
    people = cast(week)
    if not people:
        raise RuntimeError("No players to post yet: player care starts once the schedule has synced.")
    by_name = {c['name']: c for c in people}
    assign_angles(people, week)
    earlier = previous_posts(week)
    for c in people:
        c['previous'] = earlier.get(c['save_id'])
    roster_text = "; ".join(describe(c) for c in people)
    facts = game_facts()

    prompt = (f"{GUARDRAILS} Facts: {facts} The players: {roster_text}. "
              f"Write {POSTS} posts for the Wyoming team board, each by a different player from the list (use the exact name as author). "
              "Each post fits his own stat line and mood: a big game sounds proud and thanks teammates, a quiet or bench week sounds "
              "humble or hungry, a low mood shows a little in the tone without saying why. Never write the 'how he feels' words themselves. "
              "Each post follows that player's 'his post this week' angle. A post about his numbers quotes exactly one stat as the "
              "facts give it, like '177 rush yards' or '9 tackles'; never combine two stats into one claim, so '30 rec yds, 1 TD' is "
              "not 'a 30 yard TD'. Vary them: no two posts start or end the same way, never repeat a player's last post, and avoid "
              "'felt good', 'gotta keep' and thanking the o-line for holes. "
              'Respond with ONLY JSON: {"posts": [{"author": "Exact Name", "text": "post text"}, ...]}')
    posts = []
    for _attempt in range(3):
        try:
            posts = parse(ai_engine.call_ollama(selected_model, prompt, force_json=True, temperature=TEMPERATURE), by_name)
            if posts:
                break
        except Exception:
            continue
    if not posts:
        raise RuntimeError("The model didn't return any team board posts. Is Ollama running?")
    allowed = fact_check.spoken_numbers(prompt)
    posts = [{"author": p['author'], "text": drop_td_lengths(scrub(fact_check.drop_invented(ai_engine.strip_tags(p['text']), allowed), people))} for p in posts[:POSTS]]
    posts = [p for p in posts if p['text'] and not repeats(p['text'], by_name[p['author']].get('previous'))]

    numbered = " ".join(f"[{i}] {p['author']}: {p['text']}" for i, p in enumerate(posts))
    reply_prompt = (f"{GUARDRAILS} Facts: {facts} The players: {roster_text}. These posts are on the team board: {numbered} "
                    f"Write {REPLIES} short replies from teammates (a different player than the post's author; any player from the list): "
                    "hype, jokes, encouragement, the kind of thing teammates say to each other. Replies never mention stats or numbers. "
                    'Respond with ONLY JSON: {"replies": [{"author": "Exact Name", "reply_to": 0, "text": "reply text"}, ...]}')
    replies = []
    try:
        raw = parse(ai_engine.call_ollama(selected_model, reply_prompt, force_json=True, temperature=TEMPERATURE), by_name, "replies")
        allowed = fact_check.spoken_numbers(reply_prompt)
        for r in raw:
            target = r.get('reply_to')
            if isinstance(target, int) and 0 <= target < len(posts) and posts[target]['author'] != r['author']:
                text = scrub(fact_check.drop_invented(ai_engine.strip_tags(r['text']), allowed), people)
                if text and not re.search(r"\d", text):   # a reply quoting stats tends to give them to the wrong player
                    replies.append({"author": r['author'], "text": text, "reply_to": target})
    except Exception:
        pass   # the posts stand on their own

    conn = database.get_db_connection()
    conn.execute("DELETE FROM team_board_posts WHERE week = ?", (week,))
    ids = []
    for p in posts:
        cursor = conn.execute("INSERT INTO team_board_posts (week, save_id, text) VALUES (?, ?, ?)", (week, by_name[p['author']]['save_id'], p['text']))
        ids.append(cursor.lastrowid)
    for r in replies[:REPLIES]:
        conn.execute("INSERT INTO team_board_posts (week, save_id, text, reply_to) VALUES (?, ?, ?, ?)",
                     (week, by_name[r['author']]['save_id'], r['text'], ids[r['reply_to']]))
    conn.commit()
    conn.close()
    return build_page()

def build_page():
    """The newest week's board: posts in order, each with its replies."""
    conn = database.get_db_connection()
    row = conn.execute("SELECT MAX(week) AS week FROM team_board_posts").fetchone()
    week = row['week'] if row else None
    rows = [dict(r) for r in conn.execute("SELECT * FROM team_board_posts WHERE week IS ? ORDER BY post_id", (week,)).fetchall()] if week is not None else []
    conn.close()
    people = {p['save_id']: p for p in roster.query_full_roster() if p.get('save_id')}
    def author(save_id):
        p = people.get(save_id) or {}
        return {"save_id": save_id, "name": p.get('player_name', "A teammate"), "position": p.get('position', ""),
                "jersey": p.get('jersey_num'), "portrait": media.portrait_url("player", p.get('portrait_file'))}
    posts = [{"id": r['post_id'], "author": author(r['save_id']), "text": r['text'], "replies": []} for r in rows if not r['reply_to']]
    by_id = {p['id']: p for p in posts}
    for r in rows:
        if r['reply_to'] in by_id:
            by_id[r['reply_to']]['replies'].append({"author": author(r['save_id']), "text": r['text']})
    return {"week": week, "posts": posts, "count": len(rows)}

initialize_tables()
