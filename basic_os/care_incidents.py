"""Player care, off-field incidents: a rare weekly roll per player, driven mostly by neglect (empty needs, warning signs
left alone), that the coach then responds to. App-only: incidents change needs and trust, and show up in the Locker
Room, the dispatch, the campus feed, the press room and the podcast, but nothing is written to the save.

The rule from the design: scandalous incidents only ever happen to generated (generic-face) players. Real players
(their own scanned face) only get blameless ones, and the app never writes a story accusing a real person of anything."""
import random
import care
import database
import league

# Incidents. "scandal" ones are only for generated players. "hits" are need changes when it happens; "press" is how
# the media would put it (never more than the facts here).
INCIDENTS = [
    {"key": "family", "title": "Family emergency", "scandal": False, "serious": False, "hits": {"home": -25, "morale": -10},
     "text": "{name} got a call from home: a family emergency. He wants to be with his family.",
     "press": "{name} is dealing with a family matter at home"},
    {"key": "illness", "title": "Came down sick", "scandal": False, "serious": False, "hits": {"health": -25, "focus": -5},
     "text": "{name} came down with a bad flu and has been in bed for two days.", "press": "{name} has been sick this week"},
    {"key": "burnout", "title": "Running on empty", "scandal": False, "serious": False, "hits": {"focus": -20, "morale": -15},
     "text": "{name} told a trainer he's exhausted and overwhelmed, and skipped a lift to sleep.", "press": "{name} is taking a mental reset"},
    {"key": "pickup", "title": "Hurt in a pickup game", "scandal": False, "serious": True, "hits": {"health": -30, "morale": -10},
     "text": "{name} rolled an ankle playing pickup basketball at the rec center.", "press": "{name} picked up a minor injury away from football"},
    {"key": "car", "title": "Car accident (not his fault)", "scandal": False, "serious": True, "hits": {"health": -20, "morale": -10, "focus": -10},
     "text": "{name} was rear-ended at a stoplight. He's sore and shaken up, but OK.", "press": "{name} was in a minor car accident; the other driver was at fault"},
    {"key": "grief", "title": "A loss in the family", "scandal": False, "serious": False, "hits": {"home": -30, "morale": -20},
     "text": "{name}'s grandmother passed away. The funeral is this weekend.", "press": "{name} is mourning a death in the family"},
    {"key": "curfew", "title": "Missed curfew", "scandal": True, "serious": False, "hits": {"focus": -15},
     "text": "{name} missed curfew on a road trip and was seen out at 2 a.m.", "press": "{name} broke team rules on the road trip"},
    {"key": "party", "title": "Off-campus party", "scandal": True, "serious": False, "hits": {"focus": -15, "academics": -10},
     "text": "Police broke up a loud off-campus party at {name}'s place; he was cited for noise.", "press": "{name} was cited after an off-campus party"},
    {"key": "fight", "title": "Fight outside a bar", "scandal": True, "serious": True, "hits": {"health": -15, "focus": -20, "morale": -10},
     "text": "{name} got into a fight outside a bar downtown. Campus police took a report.", "press": "{name} was involved in a fight downtown"},
    {"key": "dui", "title": "Arrested for DUI", "scandal": True, "serious": True, "hits": {"focus": -25, "morale": -20, "academics": -10},
     "text": "{name} was pulled over after a night out and arrested for driving under the influence. Nobody was hurt.",
     "press": "{name} was arrested for DUI"},
]
BY_KEY = {i['key']: i for i in INCIDENTS}

def initialize_tables():
    conn = database.get_db_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS care_incidents (
        incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
        week INTEGER, save_id TEXT, name TEXT, position TEXT, incident_key TEXT,
        status TEXT DEFAULT 'open',   -- open, handled, unhandled (the week ended first)
        response TEXT, outcome TEXT,
        public INTEGER DEFAULT 1      -- 0 while "protected from the press"
    )
    """)
    conn.commit()
    conn.close()

def execute(sql, params=()):
    conn = database.get_db_connection()
    conn.execute(sql, params)
    conn.commit()
    conn.close()

def is_generated(player):
    """A generic face (no scan of his own) means a generated player; anyone else counts as real, the safe default."""
    return "Generic_" in (player.get('portrait_file') or player.get('portrait') or "")

def recently_counseled(save_id, week, tuning):
    rows = league.query_rows("SELECT week FROM care_incidents WHERE save_id = ? AND response = 'counseling' ORDER BY week DESC LIMIT 1", (save_id,))
    return bool(rows) and week - rows[0]['week'] < tuning['incidents']['counseling_weeks']

def incident_chance(player, ctx, tuning, counseled=False):
    """This week's chance of an incident: a small base, mostly raised by empty needs and open warning signs."""
    t = tuning['incidents']
    factor = 1.0
    for need in care.NEEDS:
        if player['needs'][need] < tuning['low_need']:
            factor += t['low_focus_weight'] if need == "focus" else t['low_need_weight']
    factor += t['warning_weight'] * len(player.get('warnings') or [])
    factor *= t['undisciplined'] if "Undisciplined" in player['traits'] else 1
    factor *= t['disciplined'] if "Disciplined" in player['traits'] else 1
    factor *= t['star'] if player['starter'] or player['dev'] in ("Star", "Elite") else 1
    factor *= t['big_win'] if ctx.get('big_win') else 1
    factor *= 1 - t['trust_relief'] * player['trust'] / 100
    factor *= t['counseling_factor'] if counseled else 1
    return min(t['max_chance'], t['base_chance'] * factor)

def pick_incident(player, rng, tuning):
    """Which incident: neglect (an empty Focus) leans scandalous, but only a generated player can get one."""
    options = [i for i in INCIDENTS if not i['scandal'] or is_generated(player)]
    weights = []
    for i in options:
        w = tuning['incidents']['serious_weight'] if i['serious'] else 1.0
        if i['scandal'] and player['needs']['focus'] < tuning['low_need']:
            w *= 3
        weights.append(w)
    return rng.choices(options, weights=weights)[0]

# ---------- The weekly tick (called from care.advance) ----------

def close_week(players, week, tuning):
    """An incident still open when the next week arrives went unanswered: trust and morale drop."""
    t = tuning['incidents']
    by_id = {p['save_id']: p for p in players}
    events = []
    for row in league.query_rows("SELECT * FROM care_incidents WHERE status = 'open' AND week < ?", (week,)):
        p = by_id.get(row['save_id'])
        if p:
            p['trust'] = max(0, p['trust'] - t['unanswered_trust'])
            p['needs']['morale'] = max(0, p['needs']['morale'] - t['unanswered_morale'])
            events.append((p['save_id'], "incident", f"No response to {p['name']}'s {BY_KEY[row['incident_key']]['title'].lower()}: trust -{t['unanswered_trust']}, morale -{t['unanswered_morale']}."))
        execute("UPDATE care_incidents SET status = 'unhandled', outcome = 'No response from the coach' WHERE incident_id = ?", (row['incident_id'],))
    # A story kept from the press can break a week later
    for row in league.query_rows("SELECT * FROM care_incidents WHERE public = 0 AND week < ?", (week,)):
        broke = random.Random(f"break-{row['incident_id']}").random() < t['protect_break_chance']
        execute("UPDATE care_incidents SET public = ? WHERE incident_id = ?", (1 if broke else 2, row['incident_id']))
        p = by_id.get(row['save_id'])
        if broke and p:
            p['needs']['morale'] = max(0, p['needs']['morale'] - t['story_breaks_morale'])
            events.append((p['save_id'], "incident", f"The story about {p['name']} got out anyway: morale -{t['story_breaks_morale']}."))
    return events

def roll(players, week, ctx, tuning, rng):
    """At most one incident a week for the whole team. Mutates the player hit; returns log events."""
    for p in sorted(players, key=lambda p: p['save_id']):
        if rng(p['save_id'] + "incident").random() >= incident_chance(p, ctx, tuning, recently_counseled(p['save_id'], week, tuning)):
            continue
        incident = pick_incident(p, rng(p['save_id'] + "which"), tuning)
        for need, points in incident['hits'].items():
            p['needs'][need] = max(0, p['needs'][need] + points)
        execute("INSERT INTO care_incidents (week, save_id, name, position, incident_key) VALUES (?, ?, ?, ?, ?)",
                (week, p['save_id'], p['name'], p['position'], incident['key']))
        hits = ", ".join(f"{care.NEED_LABELS[n]} {v}" for n, v in incident['hits'].items())
        return [(p['save_id'], "incident", f"Incident: {incident['text'].format(name=p['name'])} ({hits}). Respond in the Care window.")]
    return []

# ---------- The coach responds ----------

def respond(incident_id, key):
    row = next(iter(league.query_rows("SELECT * FROM care_incidents WHERE incident_id = ?", (incident_id,))), None)
    if not row or row['status'] != "open":
        raise ValueError("That incident has already been handled.")
    tuning = care.load_tuning()
    rule = tuning['incidents']['responses'].get(key)
    if not rule or key not in allowed_responses(BY_KEY[row['incident_key']], tuning):
        raise ValueError("Unknown response.")
    week = int(care.get_state("week"))
    hours = int(float(care.get_state("hours") or 0))
    if rule['hours'] > hours:
        raise ValueError(f"Not enough coach hours left this week ({hours} left, {rule['label']} takes {rule['hours']}).")
    players = care.load_players()
    p = next((p for p in players if p['save_id'] == row['save_id']), None)
    if not p:
        raise ValueError("That player isn't on the roster anymore.")
    for need, points in rule.get('needs', {}).items():
        p['needs'][need] = max(0, min(100, p['needs'][need] + points))
    p['trust'] = max(0, min(100, p['trust'] + rule.get('trust', 0)))
    if rule.get('clears_warnings'):
        p['warnings'] = []
    care.save_players(players, week)
    care.set_state("hours", hours - rule['hours'])
    outcome = rule['outcome'].format(name=p['name'])
    execute("UPDATE care_incidents SET status = 'handled', response = ?, outcome = ?, public = ? WHERE incident_id = ?",
            (key, outcome, 0 if key == "protect" else 1, incident_id))
    care.log(week, p['save_id'], "incident", f"{rule['label']}: {outcome}")
    return care.dashboard()

# ---------- For the window and the writers ----------

def allowed_responses(incident, tuning):
    """Discipline and suspension only fit an incident that was his doing (a blameless one can't be punished)."""
    return [k for k, r in tuning['incidents']['responses'].items() if incident['scandal'] or not r.get('only_for_misconduct')]

def open_incidents(tuning):
    rules = tuning['incidents']['responses']
    out = []
    for r in league.query_rows("SELECT * FROM care_incidents WHERE status = 'open' ORDER BY incident_id"):
        incident = BY_KEY[r['incident_key']]
        out.append({"incident_id": r['incident_id'], "save_id": r['save_id'], "name": r['name'], "position": r['position'], "week": r['week'],
                    "title": incident['title'], "text": incident['text'].format(name=r['name']),
                    "responses": [{"key": k, "label": rules[k]['label'], "hours": rules[k]['hours'], "effect": rules[k]['effect']}
                                  for k in allowed_responses(incident, tuning)]})
    return out

def recent(weeks=2):
    """Incidents from the last `weeks` weeks that the outside world knows about (newest first)."""
    week = int(care.get_state("week") or 0)
    return league.query_rows("SELECT * FROM care_incidents WHERE week > ? AND public != 0 ORDER BY incident_id DESC", (week - weeks,))

def story_lines():
    """Plain sentences about recent public incidents and how the coach handled them, for the dispatch, the press
    room and the podcast. Built only from the catalog's press wording (blameless for real players)."""
    lines = []
    for r in recent():
        incident = BY_KEY[r['incident_key']]
        line = incident['press'].format(name=f"{r['position']} {r['name']}")
        if r['status'] == "handled":
            line += f"; the coaches responded: {care.load_tuning()['incidents']['responses'][r['response']]['press']}"
        elif r['status'] == "unhandled":
            line += "; the coaches have not commented"
        lines.append(line + ".")
    return lines

def prompt_context():
    """A sentence for writers' prompts, or ''. Repeats that these are the only facts, so nothing worse gets invented."""
    lines = story_lines()
    if not lines:
        return ""
    return (" Off the field this week (report only these facts, never add details, charges or blame): " + " ".join(lines))

def warning_lines(limit=4):
    """Open warning signs on the team, for the Locker Room's off-field panel."""
    rows = league.query_rows("""SELECT w.week, w.need, w.text, r.player_name, r.position FROM care_warnings w
                                JOIN team_roster r ON r.save_id = w.save_id WHERE w.open = 1 ORDER BY w.warning_id DESC LIMIT ?""", (limit,))
    return [{"week": r['week'], "name": r['player_name'], "position": r['position'], "text": r['text']} for r in rows]

def locker_room():
    """The Locker Room's off-field panel: warning signs to watch and recent incidents with how they were handled."""
    incidents = []
    for r in league.query_rows("SELECT * FROM care_incidents ORDER BY incident_id DESC LIMIT 6"):
        incidents.append({"week": r['week'], "name": r['name'], "position": r['position'], "title": BY_KEY[r['incident_key']]['title'],
                          "status": r['status'], "outcome": r['outcome']})
    return {"warnings": warning_lines(), "incidents": incidents}

initialize_tables()
