import json
import re
import database
import league
import media
import recap
import roster
import save_sync

# Offseason tab: where the dynasty is in its year, who's leaving our roster, the coaching carousel, and a
# Signing Day story. In season the game hasn't worked out departures yet (its odds read -1), so the roster
# outlook uses simple app rules until the game's own odds and end-of-season lists appear, then switches to them.

STARTERS = {"WR": 3, "DT": 2, "CB": 2}   # starting spots per save position (everything else has one)
DRAFT_WATCH_OVERALL = 80                  # app rule: a junior this good is a draft candidate (three years out of high school)
TRANSFER_GAP = 3                          # app rule: a first backup within this many points of the weakest starter
ROLE_LABELS = {"hc": "Head Coach", "oc": "Offensive Coordinator", "dc": "Defensive Coordinator"}
SIGNING_PROSPECTS = 8

def initialize_offseason_tables():
    conn = database.get_db_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS offseason_columns (
        column_id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,             -- 'signing_day' or 'class_report' (before the signing period)
        title TEXT,
        body TEXT NOT NULL,
        created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()

# ---------- Where we are in the year ----------

def phase():
    data = json.loads(save_sync.get_state('phase') or "{}")
    week_type = data.get('weekType') or ""
    stage = data.get('stage') or ""
    offseason = bool(data.get('offseasonStage')) or "offseason" in stage.lower() or week_type.lower().startswith("off")
    if offseason:
        label = f"Offseason, stage {data['offseasonStage']} of {data['offseasonStages']}" if data.get('offseasonStage') and data.get('offseasonStages') else "Offseason"
    elif week_type.startswith("Bowl") or week_type == "NationalChampionship":
        label = "Bowl season"
    elif week_type == "ConferenceChampionship":
        label = "Conference championship week"
    else:
        label = f"Regular season, Week {data['week']}" if data.get('week') is not None else "Regular season"
    windows = [name for name, key in (("Coaching carousel", "carousel"), ("Staff hiring", "staffHiring"), ("Transfer portal", "transferPortal"),
                                      ("Signing period", "signing"), ("NFL draft", "draft")) if data.get(key)]
    return {"label": label, "offseason": offseason, "windows": windows, "signing": bool(data.get('signing')),
            "season_year": data.get('seasonYear')}

# ---------- Roster outlook ----------

def depth_rank(player):
    digits = re.sub(r"\D", "", player.get('depth_slot') or "")
    return int(digits) if digits else 99

def has_odds(p, key):
    """The game writes -1 until it has worked out a player's odds (at season's end)."""
    return p.get(key) is not None and p[key] >= 0

def player_view(p, note=None):
    return {"name": p['player_name'], "position": p['position'], "jersey": p['jersey_num'], "overall": p['overall'],
            "class": p['class_year'] or "", "portrait": media.portrait_url("player", p.get('portrait_file')),
            "starter": p['starter'], "note": note}

def outlook(departures):
    players = [dict(p) for p in roster.query_full_roster() if p.get('save_id')]
    by_position = {}
    for p in players:
        by_position.setdefault(p['position'], []).append(p)
    for group in by_position.values():
        group.sort(key=depth_rank)
        spots = STARTERS.get(group[0]['position'], 1)
        weakest = min(group[:spots], key=lambda x: x['overall'] or 0)
        for index, p in enumerate(group):
            p['starter'] = index < spots
            p['first_backup'] = index == spots
            p['blocked_by'] = weakest  # the starter a backup would have to beat
    by_id = {p['save_id']: p for p in players}
    order = lambda p: (not p['starter'], -(p['overall'] or 0))

    seniors = sorted((p for p in players if p['class_year'] == "Senior"), key=order)

    # Draft: the game's list once it exists, then its odds, then the app rule
    early = [by_id[i] for i in departures.get('earlyDraft', []) if i in by_id]
    odds = [p for p in players if has_odds(p, 'go_pro_chance')]
    if early:
        draft, draft_source = [player_view(p, "Declared for the draft") for p in sorted(early, key=order)], "game"
    elif odds:
        picks = sorted((p for p in odds if p['class_year'] != "Senior" and p['go_pro_chance'] > 0), key=lambda p: -p['go_pro_chance'])
        draft, draft_source = [player_view(p, f"{p['go_pro_chance']}% chance he turns pro") for p in picks], "odds"
    else:
        picks = sorted((p for p in players if p['class_year'] == "Junior" and (p['overall'] or 0) >= DRAFT_WATCH_OVERALL), key=order)
        draft, draft_source = [player_view(p, f"Rated {p['overall']}, draft-caliber for a junior") for p in picks], "estimate"

    # Transfers: same order of trust
    candidates = [by_id[i] for i in departures.get('transferCandidates', []) if i in by_id]
    odds = [p for p in players if has_odds(p, 'transfer_chance')]
    if candidates:
        transfer, transfer_source = [player_view(p, "On the game's transfer list") for p in sorted(candidates, key=order)], "game"
    elif odds:
        picks = sorted((p for p in odds if p['class_year'] != "Senior" and p['transfer_chance'] > 0), key=lambda p: -p['transfer_chance'])
        transfer, transfer_source = [player_view(p, f"{p['transfer_chance']}% chance he transfers") for p in picks], "odds"
    else:
        picks = [p for p in players if p['first_backup'] and p['class_year'] in ("Sophomore", "Junior")
                 and (p['overall'] or 0) >= (p['blocked_by']['overall'] or 0) - TRANSFER_GAP]
        transfer = [player_view(p, f"Rated {p['overall']}, stuck behind {p['blocked_by']['player_name']} ({p['blocked_by']['overall']})")
                    for p in sorted(picks, key=order)]
        transfer_source = "estimate"

    starters = [p for p in players if p['starter']]
    leaving = {p['save_id'] for p in seniors} | set(departures.get('earlyDraft', [])) | set(departures.get('transferCandidates', []))
    return {"seniors": [player_view(p, "Starter" if p['starter'] else None) for p in seniors],
            "draft": draft, "draft_source": draft_source, "transfer": transfer, "transfer_source": transfer_source,
            "starters": len(starters), "returning_starters": sum(1 for p in starters if p['save_id'] not in leaving)}

# ---------- Coaching carousel ----------

def carousel():
    teams = league.query_teams()
    rows = league.query_coaching_changes()
    moves = []
    for r in rows:
        team = teams.get(r['team_id'])
        if not team:
            continue
        came_from = next((teams.get(o['team_id']) for o in rows if o['old_name'] and o['old_name'] == r['new_name'] and o['team_id'] != r['team_id']), None)
        moves.append({"team": recap.team_view(team), "role": ROLE_LABELS.get(r['role'], r['role']), "old": r['old_name'], "new": r['new_name'],
                      "from": recap.team_view(came_from) if came_from else None,
                      "when": f"Week {r['week']}" if r['week'] and not (r['stage'] or "").lower().startswith("off") else (r['stage'] or "")})
    return moves

def hot_seat():
    """The head coaches the Coaches tab has on the hot seat: who the carousel is likeliest to claim."""
    import coaches
    return coaches.build_news()['lists']['hc']['hot'][:5]

# ---------- Signing Day ----------

STAR_WORDS = {5: "five-star", 4: "four-star", 3: "three-star", 2: "two-star", 1: "one-star"}

def recruit_line(p):
    rank = f", No. {p['national_rank']} nationally" if p.get('national_rank') else ""
    return f"{STAR_WORDS.get(p['stars'], 'unrated')} {p['position']} {p['name']}" + (f" from {p['hometown']}" if p.get('hometown') else "") + rank

def signing_facts(page, team_name):
    facts = []
    if page['commits']:
        facts.append(f"{team_name} commits ({len(page['commits'])}): " + "; ".join(recruit_line(c) for c in page['commits']) + ".")
    else:
        facts.append(f"No recruit has committed to {team_name} yet, so the class is still empty.")
    for p in page['board'][:SIGNING_PROSPECTS]:
        if p.get('committed_to'):
            continue
        leader = p['schools'][0]['name'] if p['schools'] else None
        standing = ("we lead" if p.get('leading') else f"{leader} leads, we trail by {p['behind']} influence points" if leader and p.get('behind') is not None
                    else f"{leader} leads" if leader else "wide open")
        facts.append(f"Target: {recruit_line(p)} ({standing}).")
    return " ".join(facts)

def query_column():
    rows = league.query_rows("SELECT * FROM offseason_columns ORDER BY column_id DESC LIMIT 1")
    if not rows:
        return None
    return {"kind": rows[0]['kind'], "title": rows[0]['title'],
            "paragraphs": [p.strip() for p in rows[0]['body'].split("\n\n") if p.strip()]}

def generate_signing_day(selected_model):
    import ai_engine, awards, recruiting
    page = recruiting.build_recruiting_page()
    if not page:
        raise ValueError("Sync your save first: there's no recruiting data yet.")
    us = league.query_user_team()
    signing = phase()['signing'] or phase()['offseason']
    year = (phase()['season_year'] or 0) + 1
    kind = "signing_day" if signing else "class_report"
    task = ("Write the Signing Day story: who signed, what the class means, and who got away." if signing else
            f"Write a mid-season report on the Class of {year}: who has committed, the targets still on the board, and what Signing Day could look like.")
    prompt = (f"You are a college football recruiting writer covering {us['name']}. {task} Use only these facts and never invent "
              f"recruits, rankings or quotes: {signing_facts(page, us['name'])} Group the targets by position or by where we stand instead of listing them one at a time. Write {awards.COLUMN_PARAGRAPHS} paragraphs separated by blank lines. "
              'Respond with ONLY JSON: {"title": "headline under 10 words", "body": "the story"}')
    for _attempt in range(3):
        try:
            data = json.loads(ai_engine.call_ollama(selected_model, prompt, force_json=True))
            body = awards.paragraphs(ai_engine.clean_text(str(data.get('body') or "")))
            if len(body) > 200:
                break
        except Exception:
            continue
    else:
        raise RuntimeError("The model didn't return a usable story. Is Ollama running?")
    conn = database.get_db_connection()
    conn.execute("INSERT INTO offseason_columns (kind, title, body) VALUES (?, ?, ?)",
                 (kind, ai_engine.clean_text(str(data.get('title') or "")) or ("Signing Day" if signing else f"The Class of {year}"), body))
    conn.commit()
    conn.close()
    return query_column()

# ---------- Page ----------

def build_offseason():
    departures = json.loads(save_sync.get_state('departures') or "{}")
    current = phase()
    return {"phase": current, "outlook": outlook(departures), "carousel": carousel(), "hot_seat": hot_seat(),
            "column": query_column(), "signing": current['signing'] or current['offseason'],
            "class_year": (current['season_year'] or 0) + 1 if current['season_year'] else None}

initialize_offseason_tables()
