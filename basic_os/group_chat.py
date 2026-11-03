"""The WYO Group Chat on the phone: the whole roster plus the coach. After each game the players' post-game messages
(written by team_board.py) arrive one at a time, paced like a real group chat; when the coach writes, a few players
answer, with a typing indicator first. All the pacing dials live in care_tuning.json under "chat".

Messages are written in a background thread (the model takes a while) and stored undelivered; each poll from the page
releases at most one whose delay has passed since the last delivery. So nothing floods in at once, and nothing piles
up while the app is closed: the pace simply resumes when you're back. App-only: nothing is written to the save."""
import json
import random
import re
import threading
import time
import care
import database
import league
import roster
import team_board

_lock = threading.Lock()
_jobs = {"postgame": None, "answer": None}   # the background job running, if any: {"started", "error"}

def initialize_tables():
    conn = database.get_db_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS chat_messages (
        msg_id INTEGER PRIMARY KEY AUTOINCREMENT,
        week INTEGER,
        save_id TEXT,            -- NULL: the coach
        kind TEXT,               -- postgame, reply (a teammate replying), coach, answer (to the coach)
        text TEXT,
        reply_to INTEGER,        -- the message it replies to
        delay REAL DEFAULT 0,    -- seconds after the previous delivery before it arrives
        delivered_at REAL,       -- unix time; NULL until it arrives
        read INTEGER DEFAULT 0
    )
    """)
    conn.execute("CREATE TABLE IF NOT EXISTS chat_state (state_key TEXT PRIMARY KEY, state_value TEXT)")
    conn.commit()
    conn.close()
    migrate_team_board()

def execute(sql, params=()):
    conn = database.get_db_connection()
    cursor = conn.execute(sql, params)
    conn.commit()
    conn.close()
    return cursor.lastrowid

def get_state(key):
    rows = league.query_rows("SELECT state_value FROM chat_state WHERE state_key = ?", (key,))
    return rows[0]['state_value'] if rows else None

def set_state(key, value):
    execute("INSERT OR REPLACE INTO chat_state (state_key, state_value) VALUES (?, ?)", (key, str(value)))

def tuning():
    return care.load_tuning()['chat']

def migrate_team_board():
    """The Locker Room's Team Board became the post-game chat: earlier boards move into the chat history, once."""
    if get_state("migrated") or not league.query_rows("SELECT name FROM sqlite_master WHERE name = 'team_board_posts'"):
        return
    rows = league.query_rows("SELECT * FROM team_board_posts ORDER BY week, post_id")
    newest = max((r['week'] for r in rows), default=0)
    ids = {}
    for r in rows:
        when = time.time() - (newest - r['week'] + 1) * 7 * 86400 + r['post_id']   # a week apart, in their order
        ids[r['post_id']] = execute("INSERT INTO chat_messages (week, save_id, kind, text, reply_to, delivered_at, read) VALUES (?, ?, ?, ?, ?, ?, 1)",
                                    (r['week'], r['save_id'], "reply" if r['reply_to'] else "postgame", r['text'], ids.get(r['reply_to']), when))
    if rows:
        set_state("postgame_week", newest)
    set_state("migrated", 1)

# ---------- Delivery ----------

def deliver(now=None):
    """Releases the next waiting message if its delay has passed since the last delivery. Returns it, or None."""
    now = now or time.time()
    with _lock:
        pending = league.query_rows("SELECT * FROM chat_messages WHERE delivered_at IS NULL ORDER BY msg_id LIMIT 1")
        if not pending:
            return None
        last = league.query_rows("SELECT MAX(delivered_at) AS t FROM chat_messages")[0]['t'] or 0
        if now - last < pending[0]['delay'] - 0.001:   # (a hair of slack for float time)
            return None
        execute("UPDATE chat_messages SET delivered_at = ? WHERE msg_id = ?", (now, pending[0]['msg_id']))
        return pending[0]

def typing(now=None):
    """Who is "typing…": the author of the next message when it's a few seconds from arriving, or while a reply to the
    coach is being written."""
    now = now or time.time()
    t = tuning()
    pending = league.query_rows("SELECT save_id, delay FROM chat_messages WHERE delivered_at IS NULL ORDER BY msg_id LIMIT 1")
    if pending and pending[0]['save_id']:
        last = league.query_rows("SELECT MAX(delivered_at) AS t FROM chat_messages")[0]['t'] or 0
        if pending[0]['delay'] - (now - last) <= t['typing_seconds']:
            return pending[0]['save_id']
    return "someone" if _jobs['answer'] and not _jobs['answer'].get('done') else None

def schedule(rows, first, rest, burst_max=None, burst_pause=None):
    """Delays for a batch: the first few come quickly, the rest spaced out, with a pause after every burst."""
    rng = random.Random()
    out = []
    for i, row in enumerate(rows):
        if i == 0:
            delay = rng.uniform(*first)
        elif burst_max and i % burst_max == 0:
            delay = burst_pause
        else:
            delay = rng.uniform(*rest)
        out.append({**row, "delay": round(delay, 1)})
    return out

# ---------- After a game ----------

def last_played():
    last = database.query_last_played_week()
    return last['week_id'] if last else None

def postgame_count(week):
    """More messages after a big win, fewer after a loss."""
    t = tuning()
    game = next((g for g in database.query_full_schedule() if g['week_id'] == week), None)
    if game and game['wyo_score'] is not None and game['opp_score'] is not None and game['wyo_score'] < game['opp_score']:
        return t['postgame_after_loss']
    if care.week_context(week + 1).get('big_win'):
        return t['postgame_after_big_win']
    return t['postgame_messages']

def postgame_due():
    week = last_played()
    done = get_state("postgame_week")
    return week is not None and (done is None or int(done) < week)

def start_postgame(selected_model, force=False):
    """Writes the chat for the last game in the background, once per game (force: write it again). Returns True if started."""
    week = last_played()
    job = _jobs['postgame']
    if week is None or (job and not job.get('done')) or not (force or postgame_due()):
        return False
    failed_at = float(get_state("postgame_failed_at") or 0)
    if not force and time.time() - failed_at < tuning()['retry_seconds']:
        return False
    _jobs['postgame'] = {"started": time.time()}
    threading.Thread(target=_write_postgame, args=(selected_model, week, force), daemon=True).start()
    return True

def _write_postgame(selected_model, week, force):
    t = tuning()
    try:
        count = postgame_count(week)
        posts, replies = team_board.compose(selected_model, week, count, round(count * t['replies_per_message']))
        if force:
            execute("DELETE FROM chat_messages WHERE week = ? AND kind IN ('postgame', 'reply') AND delivered_at IS NULL", (week,))
        # Teammates' replies follow the message they answer, so the chat reads in order
        ordered = []
        for i, p in enumerate(posts):
            ordered.append({**p, "kind": "postgame", "index": i})
            ordered += [{**r, "kind": "reply", "index": None} for r in replies if r['reply_to'] == i]
        ids = {}
        for row in schedule(ordered, t['first_delay'], t['delay'], t['burst_max'], t['burst_pause']):
            msg_id = execute("INSERT INTO chat_messages (week, save_id, kind, text, reply_to, delay) VALUES (?, ?, ?, ?, ?, ?)",
                             (week, row['save_id'], row['kind'], row['text'], ids.get(row.get('reply_to')), row['delay']))
            if row['index'] is not None:
                ids[row['index']] = msg_id
        set_state("postgame_week", week)
        _jobs['postgame'] = {"done": True}
    except Exception as e:
        set_state("postgame_failed_at", time.time())
        _jobs['postgame'] = {"done": True, "error": str(e)}

# ---------- The coach writes ----------

def first_names(players):
    return {p['save_id']: p['name'].split()[0].lower() for p in players}

def pick_responders(text, players, council, now=None, rng=None):
    """Who answers: anyone he named first, then a few others (captains likelier, players who are down less likely).
    Fewer when he's posting fast (the cooldown)."""
    t = tuning()
    rng = rng or random.Random()
    now = now or time.time()
    lowered = text.lower()
    named = [p['save_id'] for p in players
             if re.search(r"\b" + re.escape(p['name'].lower()) + r"\b", lowered) or re.search(r"\b" + re.escape(p['name'].split()[-1].lower()) + r"\b", lowered)
             or (len(p['name'].split()[0]) > 3 and re.search(r"\b" + re.escape(p['name'].split()[0].lower()) + r"\b", lowered))]
    last = float(get_state("coach_last_at") or 0)
    low, high = t['responders']
    count = 1 if now - last < t['cooldown_seconds'] else rng.randint(low, high)
    count = max(count, min(len(named), high))
    others = [p for p in players if p['save_id'] not in named]
    weights = [(2.0 if p['save_id'] in council else 1.3 if p['starter'] else 1.0) * (0.4 if min(p['needs'].values()) < 35 else 1.0) for p in others]
    picked = list(named)
    while len(picked) < count and others:
        choice = rng.choices(range(len(others)), weights=weights)[0]
        picked.append(others.pop(choice)['save_id'])
        weights.pop(choice)
    return picked[:max(count, len(named))], named

def send(text, selected_model):
    """The coach posts to the group: stored right away, a care lift (once a week), and players answer in the background."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Write a message first.")
    if len(text) > 500:
        raise ValueError("Keep it under 500 characters.")
    week = int(care.get_state("week") or last_played() or 0)
    now = time.time()
    execute("INSERT INTO chat_messages (week, save_id, kind, text, delivered_at, read) VALUES (?, NULL, 'coach', ?, ?, 1)", (week, text, now))
    players = care.load_players() if care.get_state("week") is not None else []
    responders, named = pick_responders(text, players, care.council_ids(), now) if players else ([], [])
    set_state("coach_last_at", now)
    care_lift(players, named, week)
    if responders:
        history = [line_for(m) for m in recent(14)][:-1]
        _jobs['answer'] = {"started": now}
        threading.Thread(target=_write_answers, args=(selected_model, text, responders, history, week), daemon=True).start()
    return view()

def _write_answers(selected_model, text, responders, history, week):
    t = tuning()
    try:
        answers = team_board.answer(selected_model, text, responders, history)
        for row in schedule(answers, t['answer_first_delay'], t['answer_delay']):
            execute("INSERT INTO chat_messages (week, save_id, kind, text, delay) VALUES (?, ?, 'answer', ?, ?)", (week, row['save_id'], row['text'], row['delay']))
        _jobs['answer'] = {"done": True}
    except Exception as e:
        _jobs['answer'] = {"done": True, "error": str(e)}

def care_lift(players, named, week):
    """A word to the whole team lifts morale a little once a care week; naming a player lifts his a little more (once a
    week per player)."""
    if not players:
        return
    t = tuning()
    by_id = {p['save_id']: p for p in players}
    changed = False
    if get_state("rally_week") != str(week):
        for p in players:
            p['needs']['morale'] = min(100, p['needs']['morale'] + t['rally_morale'])
        set_state("rally_week", week)
        care.log(week, None, "chat", f"Coach checked in with the group chat: everyone's morale +{t['rally_morale']}.")
        changed = True
    shouted = set(json.loads(get_state(f"shoutouts_{week}") or "[]"))
    for save_id in named:
        if save_id in by_id and save_id not in shouted:
            by_id[save_id]['needs']['morale'] = min(100, by_id[save_id]['needs']['morale'] + t['shoutout_morale'])
            shouted.add(save_id)
            care.log(week, save_id, "chat", f"Coach called out {by_id[save_id]['name']} in the group chat: morale +{t['shoutout_morale']}.")
            changed = True
    set_state(f"shoutouts_{week}", json.dumps(sorted(shouted)))
    if changed:
        care.save_players(players, week)

# ---------- For the page ----------

def authors():
    import media
    return {p['save_id']: {"name": p['player_name'], "position": p['position'], "jersey": p.get('jersey_num'),
                           "portrait": media.portrait_url("player", p.get('portrait_file'))}
            for p in roster.query_full_roster() if p.get('save_id')}

def recent(limit=200):
    rows = league.query_rows("SELECT * FROM chat_messages WHERE delivered_at IS NOT NULL ORDER BY delivered_at DESC, msg_id DESC LIMIT ?", (limit,))
    return list(reversed(rows))

def line_for(m, people=None):
    people = people or authors()
    who = "Coach" if m['save_id'] is None else (people.get(m['save_id']) or {}).get('name', "A teammate")
    return f"{who}: {m['text']}"

def view(since=0):
    """Delivered messages (newer than `since`), who's typing, unread count and job status, for the page's poll."""
    people = authors()
    rows = [m for m in recent() if m['msg_id'] > since]
    texts = {m['msg_id']: m for m in league.query_rows("SELECT msg_id, save_id, text FROM chat_messages WHERE msg_id IN (%s)" %
                                                         ",".join(str(m['reply_to']) for m in rows if m['reply_to']) or "0")}
    def shape(m):
        target = texts.get(m['reply_to'])
        return {"id": m['msg_id'], "me": m['save_id'] is None, "author": None if m['save_id'] is None else {"save_id": m['save_id'], **(people.get(m['save_id']) or {"name": "A teammate"})},
                "text": m['text'], "at": m['delivered_at'], "kind": m['kind'], "read": bool(m['read']),
                "reply_to": {"name": (people.get(target['save_id']) or {}).get('name', "Coach") if target['save_id'] else "Coach", "text": target['text']} if target else None}
    who = typing()
    unread = league.query_rows("SELECT COUNT(*) AS n FROM chat_messages WHERE delivered_at IS NOT NULL AND read = 0")[0]['n']
    waiting = league.query_rows("SELECT COUNT(*) AS n FROM chat_messages WHERE delivered_at IS NULL")[0]['n']
    job = _jobs['postgame'] or {}
    return {"messages": [shape(m) for m in rows], "members": len(people), "unread": unread, "waiting": waiting,
            "typing": None if not who else ("Someone" if who == "someone" else (people.get(who) or {}).get('name', "Someone")),
            "writing": bool(job and not job.get('done')), "error": None, "job_error": job.get('error')}

def poll(selected_model, since=0):
    """What the page calls every few seconds: starts the post-game chat when a new game has been played, delivers the
    next message if it's due, and returns what's new."""
    if selected_model:
        start_postgame(selected_model)
    deliver()
    return view(since)

def mark_read():
    execute("UPDATE chat_messages SET read = 1 WHERE delivered_at IS NOT NULL AND read = 0")

initialize_tables()
