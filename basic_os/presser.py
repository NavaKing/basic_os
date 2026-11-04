import hashlib
import json
import re
import database
import fact_check
import league
import media
import roster
import team
from sentences import split as sentence_split

# Press conference: the user asks questions as a reporter and our head coach or a coordinator answers in character,
# grounded in the week's facts. The week's answers are quoted in the hub generator's dispatch and posts.

ROLES = {"hc": "Head Coach", "oc": "Offensive Coordinator", "dc": "Defensive Coordinator"}
# Each coach keeps one personality (picked from his name) so he sounds like himself all season
PERSONAS = ["measured and analytical; credits his players and talks process",
            "fiery and blunt; hates excuses and says what he thinks",
            "dry sense of humor; deflects with a quip, then gives a real answer",
            "old-school; talks toughness, fundamentals and winning the line of scrimmage",
            "upbeat and energetic; clearly loves his players"]
MAX_QUESTION = 300
MAX_ANSWER_SENTENCES = 4
MIN_ANSWER_LETTERS = 20  # "..." isn't an answer
MAX_STATS = 2            # coaches don't read the box score at the podium; numbers beyond this are trimmed
# A sentence that talks about the prompt instead of football breaks character
META = re.compile(r"\b(facts?|data|information) (provided|given|available|i (have|was given))\b|\bfacts provided\b|\bthe facts\b", re.IGNORECASE)
CONTEXT_ANSWERS = 4      # earlier answers this week shown to the model so the coach stays consistent
DISPATCH_QUOTES = 3
SUGGESTIONS = 4

def initialize_presser_tables():
    conn = database.get_db_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS press_conference (
        qa_id INTEGER PRIMARY KEY AUTOINCREMENT,
        week INTEGER NOT NULL,          -- the week of the game being previewed
        role TEXT NOT NULL,
        speaker TEXT NOT NULL,
        question TEXT NOT NULL,
        answer TEXT NOT NULL,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()

# ---------- Who's at the podium ----------

def current_week():
    game = database.query_active_week()
    return game['week_id'] if game else 0

def speakers():
    """[{role, title, name, portrait}] for our head coach and coordinators."""
    row = league.query_user_team()
    staff = json.loads((row or {}).get('staff_json') or "{}")
    return [{"role": role, "title": title, "name": staff[role]['name'], "portrait": media.portrait_url("coach", staff[role].get('portrait'))}
            for role, title in ROLES.items() if (staff.get(role) or {}).get('name')]

def persona(name):
    return PERSONAS[int(hashlib.md5(name.encode("utf-8")).hexdigest(), 16) % len(PERSONAS)]

# ---------- What he knows ----------

def injury_lines():
    out = []
    for p in roster.query_full_roster():
        if p.get('save_id') and p['health_status'] not in ("Healthy", None):
            out.append(f"{roster.POSITION_NAMES.get(p['position'], p['position'])} {p['player_name']}: {p['health_status']}"
                       + (f", {p['injury_type']}" if p.get('injury_type') not in (None, "None") else "")
                       + (f", expected out {p['duration_weeks']}" if p.get('duration_weeks') not in (None, "N/A") else ""))
    return out

def week_facts(role):
    import ai_engine, rivals, scouting, storylines
    us = team.user_team()
    wins, losses = database.query_season_record()
    facts = [f"{us['full_name']} are {wins}-{losses} this season."]
    last = database.query_last_played_week()
    if last:
        facts.append(ai_engine.build_prev_context(last))
        impact = storylines.build_player_impact_lines()
        if impact:
            facts.append("Standouts last game: " + "; ".join(impact) + ".")
    game = database.query_active_week()
    if game and not game['is_played']:
        facts.append(f"Next game: Week {game['week_id']} {'at' if game.get('site') == 'Away' else 'against'} {game['opponent_name']}.")
        card = scouting.build_scouting(game)
        if card:
            facts.append(scouting.scouting_context(card))
        rival = rivals.rivalry_week()
        if rival:
            facts.append("It's rivalry week. " + rivals.rivalry_facts(rival))
    injuries = injury_lines()
    facts.append("Injury report: " + ("; ".join(injuries) + "." if injuries else "nobody is hurt."))
    context = storylines.build_storyline_context()
    if context:
        facts.append(f"Locker room storylines: {context}")
    import care_incidents
    off_field = care_incidents.prompt_context()
    if off_field:
        facts.append(off_field.strip())
    if role == "hc":   # reporters ask the head coach about his old job
        import career
        past = career.context(opponent=game['opponent_name'] if game and not game['is_played'] else None)
        if past:
            facts.append(past.strip() + " A reporter may ask him about it.")
    row = league.query_user_team() or {}
    if role == "oc" and row.get('off_rank'):
        facts.append(f"The offense ranks No. {row['off_rank']} nationally.")
    if role == "dc" and row.get('def_rank'):
        facts.append(f"The defense ranks No. {row['def_rank']} nationally.")
    return " ".join(facts)

# ---------- The press conference ----------

def transcript(week=None):
    week = current_week() if week is None else week
    rows = league.query_rows("SELECT * FROM press_conference WHERE week = ? ORDER BY qa_id", (week,))
    portraits = {s['role']: s['portrait'] for s in speakers()}
    return [{"id": r['qa_id'], "role": r['role'], "title": ROLES.get(r['role'], ""), "speaker": r['speaker'], "question": r['question'],
             "answer": r['answer'], "portrait": portraits.get(r['role'])} for r in rows]

def stat_count(text):
    return len([n for n in fact_check.spoken_numbers(text) if n >= fact_check.CHECKED_FROM])

def usable(text, allowed):
    """The answer with real words only, keeping sentences that: use numbers from the facts, stay in character (no talk of
    'facts provided'), and fit the stat budget (later sentences that would push it past MAX_STATS numbers are dropped)."""
    kept, stats = [], 0
    for sentence in sentence_split((text or "").strip().strip('"').strip()):
        if fact_check.invented_numbers(sentence, allowed) or META.search(sentence):
            continue
        if stats + stat_count(sentence) > MAX_STATS:
            continue
        stats += stat_count(sentence)
        kept.append(sentence)
    answer = " ".join(kept[:MAX_ANSWER_SENTENCES]).strip()
    return answer if sum(c.isalpha() for c in answer) >= MIN_ANSWER_LETTERS else ""

def best_answer(write, allowed, attempts=3):
    """Up to `attempts` answers; the first that talks like a coach (MAX_STATS numbers or fewer) wins, else the least stat-heavy."""
    best = ""
    for _attempt in range(attempts):
        try:
            text = usable(write(), allowed)
        except Exception:
            continue
        if text and stat_count(text) <= MAX_STATS:
            return text
        if text and (not best or stat_count(text) < stat_count(best)):
            best = text
    return best

def ask(selected_model, role, question):
    import ai_engine
    question = " ".join((question or "").split())[:MAX_QUESTION]
    if len(question) < 5:
        raise ValueError("Type a question first.")
    speaker = next((s for s in speakers() if s['role'] == role), None)
    if not speaker:
        raise ValueError("That coach isn't in the synced data.")
    us = team.user_team()
    facts = week_facts(role)
    earlier = transcript()[-CONTEXT_ANSWERS:]
    said = " ".join(f"Asked \"{q['question']}\", {q['speaker']} said: \"{q['answer']}\"" for q in earlier)
    prompt = (f"You are {speaker['name']}, {us['full_name']} {speaker['title'].lower()}, at your weekly press conference. "
              f"Your personality: {persona(speaker['name'])}. A reporter asks: \"{question}\" "
              f"Answer in the first person in 2 to {MAX_ANSWER_SENTENCES} sentences, the way a college coach talks at the podium: "
              "talk about effort, execution, matchups and the young men on the team, not like a stat sheet (one number at most). "
              "Use only the facts below: never invent stats, scores, injuries, players or opponents. If the question is about something the facts "
              "don't cover, deflect the way coaches do (\"I'm not going to get into that\", \"we'll see on Saturday\") and keep that answer short. "
              "Never say you lack information or mention facts, data or reports you were given; a coach just deflects or moves on. "
              "Every player is a man; use he/him. Never refer to yourself in the third person. "
              f"Facts: {facts} " + (f"Earlier this week: {said} Stay consistent with it. " if said else "")
              + 'Respond with ONLY JSON: {"answer": "..."}')
    allowed = fact_check.spoken_numbers(facts + " " + question + " " + said)
    answer = best_answer(lambda: ai_engine.clean_text(str(json.loads(ai_engine.call_ollama(selected_model, prompt, force_json=True)).get('answer') or "")),
                         allowed)
    if not answer:
        raise RuntimeError("The model didn't return an answer. Is Ollama running?")
    conn = database.get_db_connection()
    conn.execute("INSERT INTO press_conference (week, role, speaker, question, answer) VALUES (?, ?, ?, ?, ?)",
                 (current_week(), role, speaker['name'], question, answer))
    conn.commit()
    conn.close()
    return transcript()

def suggest_questions(selected_model):
    """A few questions a beat reporter might ask this week, built from the same facts."""
    import ai_engine
    us = team.user_team()
    prompt = (f"You are a beat reporter covering {us['full_name']}. Write {SUGGESTIONS} short, pointed questions for this week's press conference, "
              "the kind that get a coach talking: decisions, matchups, a player's development, injuries, the depth chart battles, the next opponent. "
              "Never ask trivia whose answer is just a number or a score. Each question is about a different topic in these facts: "
              f"{week_facts('hc')} "
              'Respond with ONLY JSON: {"questions": ["...", "..."]}')
    try:
        data = json.loads(ai_engine.call_ollama(selected_model, prompt, force_json=True, temperature=0.9))
    except Exception as e:
        raise RuntimeError("The model didn't return any questions. Is Ollama running?") from e
    questions = [ai_engine.clean_text(str(q)).strip() for q in data.get('questions') or [] if isinstance(q, str)]
    return [q[:MAX_QUESTION] for q in questions if len(q) > 10][:SUGGESTIONS]

def clear_week(week=None):
    conn = database.get_db_connection()
    conn.execute("DELETE FROM press_conference WHERE week = ?", (current_week() if week is None else week,))
    conn.commit()
    conn.close()

def dispatch_context():
    """This week's press conference quotes for the hub generator ('' if nobody has spoken)."""
    rows = transcript()
    if not rows:
        return ""
    picks = sorted(rows, key=lambda r: (r['role'] != "hc", -r['id']))[:DISPATCH_QUOTES]
    quotes = " ".join(f"{r['title']} {r['speaker']}, asked \"{r['question']}\", said: \"{r['answer']}\"" for r in picks)
    return f" From this week's press conference (quote these word for word if you use them; never change or invent quotes): {quotes}"

def build_page():
    return {"week": current_week(), "speakers": speakers(), "transcript": transcript()}

initialize_presser_tables()
