"""Team Board: an internal, players-only feed in the Locker Room. About 20 posts a week by our own players about the
last game and how they're feeling, with teammates replying to each other. Separate from the public campus feed.

Each player's post is grounded in his real stat line from the last game and his player care mood. Guardrails, because
most players are real college athletes: football and team topics only (no off-field life, beefs or drama), no made-up
social handles, and numbers are checked against the facts given to the model."""
import json
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

GUARDRAILS = ("Every player is a man on a men's college football team, so always use he/him/his. This is the team's private, "
              "internal board, so posts are casual, like teammates texting a group chat: short, lowercase is fine, emojis are fine. "
              "Posts are only about football, the last game, practice, teammates, coaches and the next opponent. Never write about "
              "life off the field, relationships, parties, money, NIL deals, rumors, beefs, injuries the facts don't mention, or "
              "anything negative about a named teammate. Only use numbers from the facts.")

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

def describe(c):
    played = f"last game: {c['line']}" if c['line'] else ("played but had no stats" if c['played'] else "didn't play last game (bench)")
    return f"{c['name']} ({c['class']} {c['position']}{', #' + str(c['jersey']) if c['jersey'] else ''}; {played}; how he feels, for tone only: {c['mood']})"

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
    roster_text = "; ".join(describe(c) for c in people)
    facts = game_facts()

    prompt = (f"{GUARDRAILS} Facts: {facts} The players: {roster_text}. "
              f"Write {POSTS} posts for the Wyoming team board, each by a different player from the list (use the exact name as author). "
              "Each post fits his own stat line and mood: a big game sounds proud and thanks teammates, a quiet or bench week sounds "
              "humble or hungry, a low mood shows a little in the tone without saying why. Never write the 'how he feels' words themselves. "
              f"Exactly {POSTS // 2} posts, by players with a stat line, react to their own numbers from the facts (quote one stat, "
              "like '177 yards' or '9 tackles'); the rest are about a teammate, a play, practice, the next opponent or just a vibe. Vary them: no two posts start or end the same way, and avoid 'felt good' and 'gotta keep'. "
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
    posts = [{"author": p['author'], "text": scrub(fact_check.drop_invented(ai_engine.strip_tags(p['text']), allowed), people)} for p in posts[:POSTS]]
    posts = [p for p in posts if p['text']]

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
