"""Player care, the phone and the inbox: players text the coach and school staff email him, once a week when the save
moves on. A reply or an email action is a care action (it costs coach hours); a text left unanswered when the next
week arrives drains that need and costs trust. App-only: nothing is written to the save."""
import json
import random
import care
import database
import league

# Texts by the need that's low, in two moods: "low" (under low_need) and "watch" (slipping). Mild and blameless:
# they can be about any player, real or generated.
TEXTS = {
    "morale": {"watch": ["hey coach, you got a minute this week?", "coach, honest question: am I doing enough right now?",
                         "not gonna lie coach, this week's been rough"],
               "low": ["coach I don't know what I'm doing wrong. can we talk", "starting to feel like nothing I do matters out there",
                       "coach I'm really down right now. can I come by?"]},
    "academics": {"watch": ["coach heads up, midterms are kicking my butt", "is there any way to get some extra tutoring this week?",
                            "got a big paper due same week as the game, little stressed"],
                  "low": ["coach I think I might fail this class. I need help", "advisor says my grade is slipping bad. what do I do",
                          "I'm drowning in school right now coach"]},
    "home": {"watch": ["coach my mom keeps asking when I'm coming home lol", "kinda missing home this week ngl",
                       "my little brother's game is this weekend, wish I could be there"],
             "low": ["coach I really miss my family. it's hitting hard", "been homesick all week, can't shake it",
                     "is there any way I could see my family soon? really need it"]},
    "focus": {"watch": ["coach my head's been all over the place", "can't lock in at film this week, not sure why",
                        "kinda scattered lately coach, working on it"],
              "low": ["coach I'm not right mentally right now", "I can't focus on anything. need to talk",
                      "my head's not in it coach. I don't wanna let the guys down"]},
    "health": {"watch": ["body's feeling it this week coach", "legs are heavy, think I need a little rest",
                         "sore all over after Saturday, gonna see the trainer"],
               "low": ["coach I'm beat up. really need a break", "can barely get out of bed, body's done",
                       "I'm running on empty coach"]},
}
GOOD_TEXTS = ["COACH!! did you see that?? 🔥", "Player of the Week!! thank you for believing in me coach",
              "still buzzing from Saturday coach. let's keep it going"]

# Replies the coach can send. "action" is the care action it counts as (its hours, fill and trust); None costs nothing.
REPLIES = {
    "need": [("text", "Text back", "Hang in there. I've got you, we'll figure it out."),
             ("call", "Call him", "Calling you now."),
             ("sit_down", "Bring him in", "Come by my office today. Door's open."),
             ("not_now", "Not now", "Busy this week, we'll talk later.")],
    "good": [("text", "Proud of you", "Proud of you. Keep that same energy."),
             ("call", "Call to celebrate", "Calling you, that was something special.")],
}

STAFF = {"advisor": "Academic Advisor", "trainer": "Head Athletic Trainer", "ad": "Athletic Director"}

def initialize_tables():
    conn = database.get_db_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS care_messages (
        message_id INTEGER PRIMARY KEY AUTOINCREMENT,
        week INTEGER, save_id TEXT, kind TEXT, need TEXT, text TEXT,
        status TEXT DEFAULT 'open',   -- open, answered, ignored (Not now), missed (the week ended)
        reply TEXT
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS care_emails (
        email_id INTEGER PRIMARY KEY AUTOINCREMENT,
        week INTEGER, sender TEXT, subject TEXT, body TEXT, actions_json TEXT,
        status TEXT DEFAULT 'open',   -- open, done, read (no action taken), expired
        result TEXT
    )
    """)
    conn.commit()
    conn.close()

def execute(sql, params=()):
    conn = database.get_db_connection()
    conn.execute(sql, params)
    conn.commit()
    conn.close()

# ---------- The weekly tick (called from care.advance) ----------

def close_week(players, week, tuning):
    """Texts still open when a new week arrives were left on read: the need drains and trust drops. Open emails
    expire. Mutates players; returns log events."""
    t = tuning['phone']
    by_id = {p['save_id']: p for p in players}
    events = []
    for m in league.query_rows("SELECT * FROM care_messages WHERE status = 'open' AND week < ?", (week,)):
        p = by_id.get(m['save_id'])
        if p and m['kind'] == "need":
            p['needs'][m['need']] = max(0, p['needs'][m['need']] - t['unanswered_drain'])
            p['trust'] = max(0, p['trust'] - t['unanswered_trust'])
            events.append((p['save_id'], "phone", f"{p['name']}'s text went unanswered: {care.NEED_LABELS[m['need']]} -{t['unanswered_drain']}, trust -{t['unanswered_trust']}."))
        execute("UPDATE care_messages SET status = 'missed' WHERE message_id = ?", (m['message_id'],))
    execute("UPDATE care_emails SET status = 'expired' WHERE status = 'open' AND week < ?", (week,))
    return events

def texters(players, tuning, rng):
    """Who texts this week: the players whose lowest need is under the phone line, lowest first with a little luck."""
    t = tuning['phone']
    slipping = [p for p in players if min(p['needs'].values()) < t['text_below']]
    slipping.sort(key=lambda p: min(p['needs'].values()) - rng(p['save_id'] + "phone").uniform(0, t['luck']))
    return slipping[:t['max_texts']]

def new_week(players, week, ctx, tuning, rng):
    """This week's texts and emails."""
    t = tuning['phone']
    conn = database.get_db_connection()
    used = set()   # two players never send the same text in one week (while there are others left)
    for p in texters(players, tuning, rng):
        need = min(care.NEEDS, key=lambda n: p['needs'][n])
        mood = "low" if p['needs'][need] < tuning['low_need'] else "watch"
        options = [text for text in TEXTS[need][mood] if text not in used] or TEXTS[need][mood]
        text = rng(p['save_id'] + "text").choice(options)
        used.add(text)
        conn.execute("INSERT INTO care_messages (week, save_id, kind, need, text) VALUES (?, ?, 'need', ?, ?)",
                     (week, p['save_id'], need, text))
    for p in players:
        game = p.get('game') or {}
        if game.get('award') == "national" or (game.get('award') and rng(p['save_id'] + "good").random() < t['good_text_chance']):
            conn.execute("INSERT INTO care_messages (week, save_id, kind, need, text) VALUES (?, ?, 'good', 'morale', ?)",
                         (week, p['save_id'], rng(p['save_id'] + "goodtext").choice(GOOD_TEXTS)))
    for email in staff_emails(players, week, ctx, tuning):
        conn.execute("INSERT INTO care_emails (week, sender, subject, body, actions_json) VALUES (?, ?, ?, ?, ?)",
                     (week, email['sender'], email['subject'], email['body'], json.dumps(email['actions'])))
    conn.commit()
    conn.close()

def staff_emails(players, week, ctx, tuning):
    """The staff's emails for the week: grades from the advisor, bodies from the trainer, the record from the AD."""
    inbox = tuning['inbox']
    emails = []
    grades = sorted((p for p in players if p['needs']['academics'] < inbox['advisor_below']), key=lambda p: p['needs']['academics'])[:inbox['max_names']]
    if grades:
        names = ", ".join(f"{p['name']} ({p['position']})" for p in grades)
        emails.append({"sender": "advisor", "subject": ("Exam week: " if ctx.get('exam') else "") + f"{len(grades)} player{'s' if len(grades) > 1 else ''} slipping in class",
                       "body": f"Coach, a heads-up from academics. These players are behind in at least one class: {names}. "
                               "A tutor usually turns it around in a week or two.",
                       "actions": [{"key": "tutor", "label": f"Tutor for {p['name']}", "targets": [p['save_id']]} for p in grades] +
                                  ([{"key": "study_hall", "label": "Study hall for all of them", "targets": [p['save_id'] for p in grades]}] if len(grades) > 1 else [])})
    worn = sorted((p for p in players if p['injured'] or p['needs']['health'] < inbox['trainer_below']), key=lambda p: p['needs']['health'])[:inbox['max_names']]
    if worn:
        names = ", ".join(f"{p['name']} ({p['position']}{', injured' if p['injured'] else ''})" for p in worn)
        emails.append({"sender": "trainer", "subject": "Training room report",
                       "body": f"Coach, these guys are running low and could use a lighter week: {names}. "
                               "Resting one means fewer reps for him in practice this week (it doesn't change your depth chart).",
                       "actions": [{"key": "rest", "label": f"Rest {p['name']}", "targets": [p['save_id']]} for p in worn]})
    if ctx.get('lost'):
        emails.append({"sender": "ad", "subject": "After Saturday",
                       "body": "Coach, tough one. The boosters noticed, but I'm more interested in how the locker room takes it. "
                               "Keep an eye on the guys this week.", "actions": []})
    elif ctx.get('big_win'):
        emails.append({"sender": "ad", "subject": "What a win",
                       "body": "Coach, that's the kind of win that gets people talking. Enjoy it, and make sure the guys "
                               "don't get ahead of themselves.", "actions": []})
    return emails

# ---------- The coach answers ----------

def reply(message_id, choice):
    m = next(iter(league.query_rows("SELECT * FROM care_messages WHERE message_id = ?", (message_id,))), None)
    if not m or m['status'] != "open":
        raise ValueError("That text has already been answered.")
    options = {key: (label, text) for key, label, text in REPLIES[m['kind']]}
    if choice not in options:
        raise ValueError("Unknown reply.")
    tuning = care.load_tuning()
    if choice == "not_now":
        players = care.load_players()
        p = next(p for p in players if p['save_id'] == m['save_id'])
        p['trust'] = max(0, p['trust'] - tuning['phone']['not_now_trust'])
        care.save_players(players, int(care.get_state("week")))
        care.log(int(care.get_state("week")), p['save_id'], "phone", f"Told {p['name']} not now: trust -{tuning['phone']['not_now_trust']}.")
        execute("UPDATE care_messages SET status = 'ignored', reply = ? WHERE message_id = ?", (options[choice][1], message_id))
    else:
        care.act(m['save_id'], choice, m['need'])   # raises ValueError when the hours run out
        execute("UPDATE care_messages SET status = 'answered', reply = ? WHERE message_id = ?", (options[choice][1], message_id))
    return care.dashboard()

def email_action(email_id, key):
    e = next(iter(league.query_rows("SELECT * FROM care_emails WHERE email_id = ?", (email_id,))), None)
    if not e or e['status'] != "open":
        raise ValueError("That email has already been handled.")
    if key == "read":
        execute("UPDATE care_emails SET status = 'read' WHERE email_id = ?", (email_id,))
        return care.dashboard()
    action = next((a for a in json.loads(e['actions_json']) if a['key'] == key or a['label'] == key), None)
    if not action:
        raise ValueError("Unknown email action.")
    tuning = care.load_tuning()
    rule = tuning['inbox']['actions'][action['key']]
    week = int(care.get_state("week"))
    hours = int(float(care.get_state("hours") or 0))
    if rule['hours'] > hours:
        raise ValueError(f"Not enough coach hours left this week ({hours} left, {rule['label']} takes {rule['hours']}).")
    players = care.load_players()
    by_id = {p['save_id']: p for p in players}
    names = []
    for target in action['targets']:
        p = by_id.get(target)
        if not p:
            continue
        p['needs'][rule['need']] = min(100, p['needs'][rule['need']] + rule['fill'])
        for need, points in rule.get('side_effects', {}).items():
            p['needs'][need] = max(0, min(100, p['needs'][need] + points))
        names.append(p['name'])
    care.save_players(players, week)
    care.set_state("hours", hours - rule['hours'])
    result = f"{action['label']}: {care.NEED_LABELS[rule['need']]} +{rule['fill']}" + (f" ({', '.join(names)})" if len(names) > 1 else "")
    care.log(week, None, "inbox", result)
    # Other actions in the same email stay available (a second tutor), so the email stays open until marked read
    remaining = [a for a in json.loads(e['actions_json']) if a['label'] != action['label']]
    execute("UPDATE care_emails SET actions_json = ?, status = ?, result = COALESCE(result || ' · ', '') || ? WHERE email_id = ?",
            (json.dumps(remaining), "open" if remaining else "done", result, email_id))
    return care.dashboard()

# ---------- For the window ----------

def phone_view(week, by_id):
    """Threads, newest activity first: every text and reply with each player, and whether one is waiting."""
    threads = {}
    for m in league.query_rows("SELECT * FROM care_messages ORDER BY message_id"):
        p = by_id.get(m['save_id'])
        if not p:
            continue
        thread = threads.setdefault(m['save_id'], {"save_id": m['save_id'], "name": p['name'], "position": p['position'],
                                                    "portrait": p['portrait'], "messages": [], "waiting": None, "last": 0})
        thread['messages'].append({"week": m['week'], "text": m['text'], "reply": m['reply'], "status": m['status']})
        thread['last'] = m['message_id']
        if m['status'] == "open":
            thread['waiting'] = {"message_id": m['message_id'], "replies": [{"key": k, "label": label} for k, label, _ in REPLIES[m['kind']]]}
    return sorted(threads.values(), key=lambda t: (t['waiting'] is None, -t['last']))

def inbox_view():
    rows = league.query_rows("SELECT * FROM care_emails ORDER BY (status = 'open') DESC, email_id DESC LIMIT 30")
    tuning = care.load_tuning()
    out = []
    for e in rows:
        actions = []
        for a in json.loads(e['actions_json'] or "[]"):
            rule = tuning['inbox']['actions'][a['key']]
            actions.append({"key": a['label'], "label": a['label'], "hours": rule['hours'],
                            "effect": f"{care.NEED_LABELS[rule['need']]} +{rule['fill']}" +
                                      "".join(f", {care.NEED_LABELS[n]} {v:+d}" for n, v in rule.get('side_effects', {}).items())})
        out.append({"email_id": e['email_id'], "week": e['week'], "sender": STAFF.get(e['sender'], e['sender']), "subject": e['subject'],
                    "body": e['body'], "status": e['status'], "result": e['result'], "actions": actions if e['status'] == "open" else []})
    return out

def unread():
    """(texts waiting, emails open) for the tab bar badge."""
    texts = league.query_rows("SELECT COUNT(*) AS n FROM care_messages WHERE status = 'open'")[0]['n']
    emails = league.query_rows("SELECT COUNT(*) AS n FROM care_emails WHERE status = 'open'")[0]['n']
    return texts, emails

def open_incident_count():
    import care_incidents   # noqa: F401  (makes sure the table exists)
    return league.query_rows("SELECT COUNT(*) AS n FROM care_incidents WHERE status = 'open'")[0]['n']

initialize_tables()
