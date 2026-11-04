"""The players' voices for the WYO Group Chat (group_chat.py stores and paces them): the post-game messages our own
players send after each game, teammates replying to each other, and their answers when the coach writes to the chat.
Separate from the public campus feed.

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

POSTS = 12      # post-game messages (group_chat.py picks the count per game; this is the default)
REPLIES = 8     # teammates replying to those
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
# How players answer the coach: one style each, so four answers don't all read "got it, coach"
# How the coach's message reads decides how the team answers it: nobody pivots to the next opponent when he sends "text me ;)"
PLAYFUL = re.compile(r"(;\)|;-\)|:\)|:-\)|;p|:p|:d|xd|\blol\b|\blmao\b|\bha(ha)+\b|\bjk\b|[😉😜😏😂🤣😎🙃😝😛🤪👀😅])", re.IGNORECASE)
QUESTION = re.compile(r"\?\s*$|^(how|hows|how's|what|whats|what's|who|whos|who's|why|when|where|wheres|anyone|any|are|is|do|does|did|can|could|would|should|will|sup|wyd)\b", re.IGNORECASE)
TONE_STYLES = {
    "playful": ["laughs at it", "teases the coach back, respectfully", "asks if he's joking or if someone stole his phone", "plays along with the joke",
                "points out the typo or the weird wording, if there is one, with a laugh"],
    "question": ["answers his question honestly in his own mood", "answers for the position group", "answers and adds a little joke",
                 "answers short and direct"],
}

TONE_NOTES = {
    "playful": "He's being playful or joking around (look at the winky face, emoji or wording), so the team reacts to THAT: they "
               "laugh, tease him back, play along, or ask if he's joking. Nobody pivots to football or the next opponent.",
    "question": "He asked the team a question, so they answer it, with the real names from the depth chart. Once one player has "
                "given the answer, the others don't just repeat it: they add something of their own (hype for the guy, a joke, a "
                "promise). The player the coach asked about answers as himself ('that's me, coach'); nobody else ever claims "
                "to be him.",
    "plain": "",
}

def coach_tone(text):
    """'playful' (a winky face, lol, a joke), 'question', or 'plain'."""
    if PLAYFUL.search(text or ""):
        return "playful"
    if QUESTION.search((text or "").strip()):
        return "question"
    return "plain"

REPLY_STYLES = ["fired up and ready", "hypes up a teammate the coach mentioned (or another one by name)", "a little joke or some banter",
                "short and serious, all business", "looks ahead to the next opponent", "promises something specific for practice this week"]
TOO_SIMILAR = 0.6
# "that's me, coach" from anyone but the player the coach asked about makes no sense, whatever the model says
CLAIMS = re.compile(r"\b(that'?s me|it'?s me|its me|right here|here coach|i'?m (your|the) (qb|hb|rb|wr|te|starter|guy|backup))\b|^me[,.! ]", re.IGNORECASE)
COPY_MIN_LENGTH = 20   # "on it coach" and "yes coach" look alike letter by letter; only judge replies long enough to be a copied line   # a post this close to his previous one is dropped

GUARDRAILS = ("Every player is a man on a men's college football team, so always use he/him/his. This is the team's private "
              "group chat, so messages are casual, like teammates texting: short, lowercase is fine, emojis are fine. "
              "Posts are only about football, the last game, practice, teammates, coaches and the next opponent. Never write about "
              "life off the field, relationships, parties, money, NIL deals, rumors, beefs, injuries the facts don't mention, or "
              "anything negative about a named teammate. Only use numbers from the facts. Each player's 'how he feels' note is private to "
              "him: only his own post may hint at it, and nobody ever mentions another player's mood, health, school or personal life.")

# Each player's texting voice, stable for the whole dynasty (the save has no personality data, so the app assigns one):
# the same voice in his care texts and in the group chat, so players stop sounding alike
VOICES = ["laid-back and funny, lots of 'lol'", "quiet, few words, all lowercase", "intense competitor, short and fired up",
          "polite 'yes sir' type, proper punctuation", "hype man, heavy on emojis", "big-brother leader, encouraging",
          "nervous energy, overexplains a little", "dry, deadpan humor", "country boy, easygoing, says 'y'all'",
          "city kid, quick slang", "goofy jokester, always has a bit", "serious and focused, film-room guy"]

def voice(save_id):
    return random.Random(f"voice-{save_id}").choice(VOICES)

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
    if needs['morale'] >= 85:
        return "on top of the world"
    if needs['morale'] >= 75:
        return "feeling great and confident"
    if needs[lowest] < tuning['low_need']:
        return {"morale": "down and frustrated", "academics": "stressed, buried in schoolwork", "home": "homesick",
                "focus": "distracted, head not fully in it", "health": "worn down and sore"}[lowest]
    if needs[lowest] < tuning['watch_need']:
        return {"morale": "a little down", "academics": "busy with school", "home": "missing home a bit",
                "focus": "a little scattered", "health": "banged up"}[lowest]
    return "in a good place"

def cast(week, everyone=False):
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
                    "grade": grade(stats) if stats and stats.get('DOWNSPLAYED') else None, "voice": voice(p['save_id']),
                    "starter": p['starter'], "slot": p.get('slot'), "played": bool(stats and stats.get('DOWNSPLAYED')), "mood": mood,
                    "stands_out": mood != "in a good place"})
    out.sort(key=lambda c: (-c['impact'], not c['stands_out'], not c['starter'], c['name']))
    if everyone:
        return out
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
    """{save_id: his most recent post-game message from an earlier week}."""
    conn = database.get_db_connection()
    rows = conn.execute("SELECT save_id, text FROM chat_messages WHERE kind = 'postgame' AND save_id IS NOT NULL AND week < ? ORDER BY msg_id",
                        (week or 0,)).fetchall()
    conn.close()
    return {r['save_id']: r['text'] for r in rows}

def describe(c):
    played = (f"last game: {c['line']}" + (f", {GRADE_WORDS[c['grade']]}" if c.get('grade') else "") if c['line']
              else ("played but had no stats" if c['played'] else "didn't play last game (bench)"))
    slot = f", {c['slot']} on the depth chart" if c.get('slot') else ""
    text = f"{c['name']} ({c['class']} {c['position']}{', #' + str(c['jersey']) if c['jersey'] else ''}{slot}; {played}; how he feels, for tone only: {c['mood']}"
    if c.get('voice'):
        text += f"; how he texts: {c['voice']}"
    if c.get('angle'):
        text += f"; his post this week: {c['angle']}"
    if c.get('previous'):
        text += f"; his last post, never repeat it or reuse its wording: \"{c['previous']}\""
    return text + ")"

def starters_fact():
    """The real depth chart starters, so nobody guesses who QB1 is."""
    rows = [p for p in roster.query_full_roster() if (p.get('depth_slot') or "").endswith("1") and not (p.get('depth_slot') or "")[-2:-1].isdigit()]
    rows.sort(key=lambda p: p['depth_slot'])
    return ("Depth chart starters (use these exact names, never guess one): " + "; ".join(f"{p['depth_slot']} {p['player_name']}" for p in rows) + ".") if rows else ""

def about(addressed_ids):
    """A fact line naming the players he named or addressed by spot, e.g. "The coach is asking about: QB2 Mason Drube."."""
    if not addressed_ids:
        return ""
    people = {p['save_id']: p for p in roster.query_full_roster()}
    names = [f"{people[i].get('depth_slot') or people[i]['position']} {people[i]['player_name']}" for i in addressed_ids if i in people]
    return f" The coach is talking to or asking about: {', '.join(names)}." if names else ""

def game_facts():
    import ai_engine
    last = database.query_last_played_week()
    nxt = database.query_active_week()
    facts = [ai_engine.build_prev_context(last)] if last else []
    wins, losses = database.query_season_record()
    if wins + losses:
        now = nxt['week_id'] if nxt and not nxt['is_played'] else ((last['week_id'] + 1) if last else 1)   # this week's poll
        standing = care.team_standing(now, {g['week_id']: g for g in database.query_full_schedule()})
        facts.append(f"Wyoming is {wins}-{losses}" + (f", on {care.a_or_an(standing['streak'])} {standing['streak']}-game win streak" if standing['streak'] >= 3 else "") +
                     (f", ranked No. {standing['rank']} in the AP poll" + (" for the first time, a huge milestone for the school" if standing.get('first_ranked') else "")
                      if standing['rank'] else "") + ".")
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

def clean(text, people, allowed):
    import ai_engine
    return drop_td_lengths(scrub(fact_check.drop_invented(ai_engine.strip_tags(text), allowed), people))

def ask(selected_model, prompt, names, key):
    import ai_engine
    for _attempt in range(3):
        try:
            items = parse(ai_engine.call_ollama(selected_model, prompt, force_json=True, temperature=TEMPERATURE), names, key)
            if items:
                return items
        except Exception:
            continue
    return []

def compose(selected_model, week, posts_count=POSTS, replies_count=REPLIES):
    """The post-game chat for `week`: ([{save_id, text}], [{save_id, text, reply_to: index into the posts}]). Raises
    RuntimeError when there's nobody to post or the model doesn't answer."""
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
              f"Write {posts_count} messages for the Wyoming team group chat after the game, each by a different player from the list "
              "(use the exact name as author). "
              "Each message fits his own stat line and mood: a big game sounds proud and thanks teammates, a quiet or bench week sounds "
              "humble or hungry, a low mood shows a little in the tone without saying why. Never write the 'how he feels' words themselves. "
              "Each message follows that player's 'his post this week' angle. A message about his numbers quotes exactly one stat as the "
              "facts give it, like '177 rush yards' or '9 tackles'; never combine two stats into one claim, so '30 rec yds, 1 TD' is "
              "not 'a 30 yard TD'. Vary them: no two start or end the same way, never repeat a player's last post, and avoid "
              "'felt good', 'gotta keep' and thanking the o-line for holes. "
              'Respond with ONLY JSON: {"posts": [{"author": "Exact Name", "text": "message text"}, ...]}')
    raw = ask(selected_model, prompt, by_name, "posts")
    if not raw:
        raise RuntimeError("The model didn't return any group chat messages. Is Ollama running?")
    allowed = fact_check.spoken_numbers(prompt)
    posts = [{"author": r['author'], "text": clean(r['text'], people, allowed)} for r in raw[:posts_count]]
    posts = [p for p in posts if p['text'] and not repeats(p['text'], by_name[p['author']].get('previous'))]

    replies = []
    if posts and replies_count:
        numbered = " ".join(f"[{i}] {p['author']}: {p['text']}" for i, p in enumerate(posts))
        reply_prompt = (f"{GUARDRAILS} Facts: {facts} The players: {roster_text}. These messages are in the group chat: {numbered} "
                        f"Write {replies_count} short replies from teammates (a different player than the message's author; any player from the list): "
                        "hype, jokes, encouragement, the kind of thing teammates say to each other. Replies never mention stats or numbers. "
                        'Respond with ONLY JSON: {"replies": [{"author": "Exact Name", "reply_to": 0, "text": "reply text"}, ...]}')
        allowed = fact_check.spoken_numbers(reply_prompt)
        for r in ask(selected_model, reply_prompt, by_name, "replies"):
            target = r.get('reply_to')
            if isinstance(target, int) and 0 <= target < len(posts) and posts[target]['author'] != r['author']:
                text = scrub(fact_check.drop_invented(r['text'], allowed), people)
                if text and not re.search(r"\d", text):   # a reply quoting stats tends to give them to the wrong player
                    replies.append({"author": r['author'], "text": text, "reply_to": target})
    sid = lambda name: by_name[name]['save_id']
    return ([{"save_id": sid(p['author']), "text": p['text']} for p in posts],
            [{"save_id": sid(r['author']), "text": r['text'], "reply_to": r['reply_to']} for r in replies[:replies_count]])

def answer(selected_model, coach_text, responder_ids, history, addressed_ids=()):
    """Replies from `responder_ids` (in that order) to the coach's message. history: recent chat lines, oldest first.
    Returns [{save_id, text}]."""
    import ai_engine
    last = database.query_last_played_week()
    people = [c for c in cast(last['week_id'] if last else None, everyone=True) if c['save_id'] in responder_ids]
    people.sort(key=lambda c: responder_ids.index(c['save_id']))
    if not people:
        return []
    by_name = {c['name']: c for c in people}
    tone = coach_tone(coach_text)
    asked_names = " and ".join(c['name'] for c in people if c['save_id'] in addressed_ids) or "the player the coach asked about"
    pool = TONE_STYLES.get(tone, REPLY_STYLES)
    styles = random.Random(coach_text).sample(pool, len(pool))
    for i, c in enumerate(people):
        c['angle'] = styles[i % len(styles)]   # each answer a different way, so it isn't "got it coach" four times
        c['previous'] = None
        # Only the player he's asking about may say "that's me" (QB1 answered "it's me" to "where my QB2 at")
        if c['save_id'] in addressed_ids:
            c['angle'] += "; the coach is talking to or about HIM"
        elif addressed_ids:   # the others back up the player he asked about instead of answering for him
            c['angle'] = f"hypes up {asked_names} by name; he is NOT the one the coach asked about"
    roster_text = "; ".join(describe(c) for c in people)
    prompt = (f"{GUARDRAILS} Facts: {game_facts()} Recent group chat: {' | '.join(history[-12:]) or '(quiet)'} "
              f"{starters_fact()}{about(addressed_ids)} Coach just wrote to the whole team: \"{coach_text}\" {TONE_NOTES[tone]} "
              f"The players answering, in this order: {roster_text}. Write one short reply from each of them to the coach, in order. "
              "They answer what he actually said, in their own voice and mood, respectfully but casually (it's still the head coach). "
              "If he called someone out by name or by depth chart spot or position (like 'QB1' or 'the o-line'), that player answers "
              "first. If the coach is correcting someone (fewer turnovers, missed blocks), that player owns it seriously and nobody "
              "laughs at it. Each reply follows that player's 'his post this week' style "
              "and picks up something specific the coach said. No two replies start the same way, and none repeats a line or joke "
              "already in the recent chat; never 'got it', 'will do' or 'appreciate it'. Replies never mention stats or numbers. "
              'Respond with ONLY JSON: {"replies": [{"author": "Exact Name", "text": "reply text"}, ...]}')
    out = []
    said = [line.split(": ", 1)[-1] for line in history[-12:]]
    asked = {c['name'] for c in people if c['save_id'] in addressed_ids}
    for r in ask(selected_model, prompt, by_name, "replies"):
        text = scrub(ai_engine.strip_tags(r['text']), people)
        if not text or re.search(r"\d", text) or r['author'] in [o['author'] for o in out]:
            continue
        is_asked = r['author'] in asked
        copied = len(text) >= COPY_MIN_LENGTH and any(repeats(text, line) for line in said + [o['text'] for o in out])
        if copied and not is_asked:   # no copied jokes
            continue
        if copied:   # the player he asked always answers, but not with last time's joke: just "right here, coach."
            text = sentences.split(text)[0]
        if asked and not is_asked and CLAIMS.search(text):   # only the player he asked can say "that's me"
            continue
        out.append({"author": r['author'], "text": text})
    return [{"save_id": by_name[o['author']]['save_id'], "text": o['text']} for o in out[:len(people)]]

# What players start talking about between games, with how often each comes up
TOPICS = [("something that happened at practice today", 3), ("film study for the next opponent", 2),
          ("harmless locker-room banter: food, music, a video game, a bet on something silly", 3), ("getting hyped for the next game", 2),
          ("a question for the coach about practice, the plan or the next opponent", 1.5), ("shouting out a teammate's hard work this week", 2),
          ("the weight room or recovery", 1)]

def chatter(selected_model, starter_id, replier_ids, history, rng=None):
    """A conversation a player starts between games: [{save_id, text}], the starter first. The topic is picked at random."""
    rng = rng or random.Random()
    topic = rng.choices([t for t, _ in TOPICS], weights=[w for _, w in TOPICS])[0]
    last = database.query_last_played_week()
    everyone = {c['save_id']: c for c in cast(last['week_id'] if last else None, everyone=True)}
    people = [everyone[i] for i in [starter_id] + list(replier_ids) if i in everyone]
    if len(people) < 2:
        return []
    for c in people:
        c['angle'], c['previous'] = None, None
    starter = people[0]
    by_name = {c['name']: c for c in people}
    prompt = (f"{GUARDRAILS} Facts: {game_facts()} {starters_fact()} Recent group chat: {' | '.join(history[-10:]) or '(quiet)'} "
              f"It's midweek, no game today. {starter['name']} starts a new conversation in the team group chat about {topic}; then "
              f"{', '.join(c['name'] for c in people[1:])} reply to him and each other, in that order. The players: "
              + "; ".join(describe(c) for c in people) + ". Each message sounds like that player (how he texts), short like real texts, "
              "nobody repeats a line or joke already in the recent chat, and if the starter asks the coach something, the others "
              "can chime in but don't answer for the coach. No stats or numbers. "
              'Respond with ONLY JSON: {"messages": [{"author": "Exact Name", "text": "message text"}, ...]}')
    out = []
    said = [line.split(": ", 1)[-1] for line in history[-10:]]
    for r in ask(selected_model, prompt, by_name, "messages"):
        text = scrub(r['text'], people)
        if text and not re.search(r"\d", text) and not any(repeats(text, line) for line in said if len(text) >= COPY_MIN_LENGTH):
            out.append({"save_id": by_name[r['author']]['save_id'], "text": text})
    if not out or out[0]['save_id'] != starter['save_id']:   # the conversation has to start with the starter
        return []
    return out[:len(people) + 1]

initialize_tables()
