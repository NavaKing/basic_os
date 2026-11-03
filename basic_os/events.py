import base64
import difflib
import json
import os
import re
import uuid
import requests
import database
import league

# Post-game screenshots for the weekly podcast: the user uploads the scoring summary, the vision model reads it,
# and the user checks the result before podcast.py writes and records the episode.
# Uploaded screenshots are deleted once an episode has been made from them.

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads", "events")
OLLAMA = "http://localhost:11434"

BOARD_PROMPT = ("This is a post-game stats screen from a college football video game. Read the final score exactly. "
                'Respond with ONLY JSON: {"teams": [{"abbr": "team abbreviation", "name": "team name", "final": 0}, {...}]} with the top row first.')
PLAYS_PROMPT = ("This is a scoring summary list from a college football video game. Quarter headings (First Quarter, Second Quarter...) group the lines below them. "
                "Copy every line exactly, letter for letter, including partly visible ones only if fully readable. "
                'Respond with ONLY JSON: {"plays": [{"quarter": 1, "team": "abbreviation inside the parentheses", "text": "rest of the line before the clock", "clock": "m:ss"}]}')
QUARTER_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "overtime": 5}

def initialize_event_tables():
    conn = database.get_db_connection()
    # Retired: written stories were replaced by podcast episodes
    conn.execute("DROP TABLE IF EXISTS current_events")
    # The screenshots' reading, kept until the user generates (so a page reload doesn't lose their edits)
    conn.execute("CREATE TABLE IF NOT EXISTS event_draft (draft_id INTEGER PRIMARY KEY CHECK (draft_id = 1), draft_json TEXT NOT NULL)")
    conn.commit()
    conn.close()

# ---------- Uploads ----------

def save_upload(full_data_url, summary_data_url, original_name):
    """Stores one screenshot (a downscaled full copy for the score, a full-resolution crop of the scoring list)."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    upload_id = uuid.uuid4().hex[:12]
    for suffix, data_url in (("full", full_data_url), ("summary", summary_data_url)):
        header, _, payload = (data_url or "").partition(",")
        if not header.startswith("data:image/"):
            raise ValueError("Uploads must be images.")
        with open(os.path.join(UPLOAD_DIR, f"{upload_id}_{suffix}.png"), "wb") as f:
            f.write(base64.b64decode(payload))
    with open(os.path.join(UPLOAD_DIR, f"{upload_id}_name.txt"), "w", encoding="utf-8") as f:
        f.write(os.path.basename(original_name or "screenshot")[:120])
    return upload_id

def list_uploads():
    if not os.path.isdir(UPLOAD_DIR):
        return []
    ids = sorted({name.split("_")[0] for name in os.listdir(UPLOAD_DIR) if name.endswith("_full.png")},
                 key=lambda i: os.path.getmtime(os.path.join(UPLOAD_DIR, f"{i}_full.png")))
    uploads = []
    for upload_id in ids:
        name_file = os.path.join(UPLOAD_DIR, f"{upload_id}_name.txt")
        name = open(name_file, encoding="utf-8").read() if os.path.exists(name_file) else upload_id
        uploads.append({"id": upload_id, "name": name, "thumb": f"/events/uploads/{upload_id}_full.png"})
    return uploads

def upload_path(file_name):
    """Absolute path of an upload file, or None (only plain names from our folder are served)."""
    if not re.fullmatch(r"[0-9a-f]{12}_(full|summary)\.png", file_name or ""):
        return None
    path = os.path.join(UPLOAD_DIR, file_name)
    return path if os.path.exists(path) else None

def delete_upload(upload_id):
    if not re.fullmatch(r"[0-9a-f]{12}", upload_id or ""):
        return
    for suffix in ("full.png", "summary.png", "name.txt"):
        path = os.path.join(UPLOAD_DIR, f"{upload_id}_{suffix}")
        if os.path.exists(path):
            os.remove(path)

def clear_uploads():
    for upload in list_uploads():
        delete_upload(upload['id'])

# ---------- Reading the screenshots ----------

def vision_model(preferred=None):
    """A model Ollama reports as able to see images (the selected one if it can)."""
    names = [m['name'] for m in requests.get(f"{OLLAMA}/api/tags", timeout=10).json().get('models', [])]
    for name in ([preferred] if preferred in names else []) + names:
        info = requests.post(f"{OLLAMA}/api/show", json={"model": name}, timeout=10).json()
        if "vision" in (info.get('capabilities') or []):
            return name
    raise RuntimeError("None of your Ollama models can read images. cfb-gemma or another Gemma 3 vision model is needed.")

def ask_image(model, path, prompt):
    with open(path, "rb") as f:
        image = base64.b64encode(f.read()).decode()
    res = requests.post(f"{OLLAMA}/api/generate", json={"model": model, "prompt": prompt, "images": [image], "stream": False,
                                                        "format": "json", "options": {"temperature": 0}}, timeout=300)
    res.raise_for_status()
    return json.loads(res.json().get('response') or "{}")

def clock_seconds(clock):
    match = re.match(r"(\d+):(\d\d)", clock or "")
    return int(match.group(1)) * 60 + int(match.group(2)) if match else None

def play_key(play):
    """Identifies the same play seen in two screenshots (the reading may differ by a letter, so use team + clock + first word)."""
    first_word = re.sub(r"[^a-z]", "", (play['text'].split() or [""])[0].lower())
    return (play['team'].upper(), play['clock'], first_word)

def merge_plays(readings):
    """Joins the plays from every screenshot in game order and fixes up quarters.
    Screenshots are scrolled views of one list, so each is an in-order slice. A quarter heading scrolled off-screen
    makes the model under-count the quarter, so take the highest quarter any screenshot gave, and start a new quarter
    whenever the game clock goes back up."""
    order, seen = [], {}
    for plays in readings:
        previous = None
        for play in plays:
            key = play_key(play)
            if key in seen:
                seen[key]['quarters'].append(play['quarter'])
                previous = key
                continue
            entry = {**play, "quarters": [play['quarter']]}
            seen[key] = entry
            # Put it right after the play before it in this screenshot (keeps game order when screenshots overlap)
            position = order.index(previous) + 1 if previous in order else len(order)
            order.insert(position, key)
            previous = key
    merged, quarter, last_clock = [], 1, None
    for key in order:
        play = seen.pop(key) if key in seen else None
        if not play:
            continue
        clock = clock_seconds(play['clock'])
        if last_clock is not None and clock is not None and clock > last_clock:
            quarter += 1
        quarter = max(quarter, max(q for q in play['quarters'] if isinstance(q, int)) if any(isinstance(q, int) for q in play['quarters']) else quarter)
        last_clock = clock if clock is not None else last_clock
        play.pop('quarters')
        merged.append({**play, "quarter": quarter})
    return merged

PLAY_PATTERN = re.compile(
    r"^(?P<player>.+?),?\s+(?P<yards>\d+)\s+Yd\s+(?P<kind>pass|run|interception return|fumble return|punt return|kickoff return|field goal|fg|blocked [a-z]+ return)"
    r"(?:\s+from\s+(?P<passer>[^(]+?))?\s*(?:\((?P<extra>[^)]*)\))?\s*,?\s*$", re.IGNORECASE)

# Plays built from the save have no yardage: "Jackson Holman touchdown catch from Tyler Hughes (kick)", "Field goal", "Safety",
# "Jo Smith interception return touchdown (kick)"
SAVE_PLAY_PATTERN = re.compile(r"^(?:(?P<player>.+?)\s+)?(?:(?P<ret>interception|fumble|kickoff|punt) return\s+)?touchdown(?:\s+(?P<kind>run|catch|pass))?"
                               r"(?:\s+from\s+(?P<passer>[^(]+?))?\s*(?:\((?P<extra>[^)]*)\))?$", re.IGNORECASE)

def conversion_points(extra):
    extra = (extra or "").lower()
    if re.search(r"fail|miss|block|no good", extra):
        return 0
    if re.search(r"two.point|2.?pt|conversion", extra):
        return 2
    return 1 if "kick" in extra else 0

def parse_play(text):
    """'Jackson Holman 1 Yd pass from Tyler Hughes (Erik Sandvik kick)' -> scorer, yards, kind, passer, points."""
    text = (text or "").strip().rstrip(",")
    match = PLAY_PATTERN.match(text)
    if not match:
        lowered = text.lower()
        if lowered.startswith("field goal"):
            return {"player": None, "yards": None, "kind": "field goal", "passer": None, "points": 3}
        save = SAVE_PLAY_PATTERN.match(text)
        if save:
            kind = (f"{save.group('ret').lower()} return" if save.group('ret') else
                    {"catch": "pass", "pass": "pass", "run": "run"}.get((save.group('kind') or "").lower(), "touchdown"))
            return {"player": (save.group('player') or "").strip() or None, "yards": None, "kind": kind,
                    "passer": (save.group('passer') or "").strip() or None, "points": 6 + conversion_points(save.group('extra'))}
        safety = "safety" in text.lower()
        return {"player": None, "yards": None, "kind": "safety" if safety else "score", "passer": None, "points": 2 if safety else 0}
    kind = match.group('kind').lower()
    extra = (match.group('extra') or "").lower()
    if kind in ("field goal", "fg"):
        points = 3
    else:
        points = 6
        if "kick" in extra and not re.search(r"fail|miss|block|no good", extra):
            points += 1
        elif re.search(r"two.point|2.?pt|conversion", extra) and not re.search(r"fail|no good", extra):
            points += 2
    return {"player": match.group('player').strip(), "yards": int(match.group('yards')), "kind": kind,
            "passer": (match.group('passer') or "").strip() or None, "points": points}

def roster_names(team_ids):
    names = {}
    for team_id in team_ids:
        roster = league.query_plan_roster(team_id) if team_id is not None else None
        for p in (roster or {}).get('players', []):
            names[p['name']] = {**p, "team_id": team_id}
    return names

def fix_names(text, names):
    """Swaps a misread player name for the closest real one on either roster ('Diorre Hubbard' -> 'Diore Hubbard')."""
    parsed = parse_play(text)
    for name in (parsed['player'], parsed['passer']):
        if name and name not in names:
            close = difflib.get_close_matches(name, list(names), n=1, cutoff=0.8)
            if close:
                text = text.replace(name, close[0])
    return text

def match_team(abbr, name):
    teams = league.query_teams().values()
    abbr, name = (abbr or "").upper(), (name or "").lower()
    return next((t for t in teams if (t['short_name'] or "").upper() == abbr), None) or \
        next((t for t in teams if name and t['name'].lower() == name), None)

def build_draft(teams, plays, finals):
    """Adds per-quarter scores (from the plays) and warnings to a reading the user can review."""
    for p in plays:
        p['points'] = parse_play(p['text'])['points']
    warnings = []
    for t in teams:
        quarters = [0, 0, 0, 0]
        for p in plays:
            if p['team'].upper() == t['abbr'].upper():
                while len(quarters) < p['quarter']:
                    quarters.append(0)  # overtime
                quarters[p['quarter'] - 1] += p['points']
        t['quarters'] = quarters
        t['total'] = sum(quarters)
        if finals.get(t['abbr'].upper()) is not None and finals[t['abbr'].upper()] != t['total']:
            warnings.append(f"{t['abbr']}: the scoring plays add up to {t['total']} but the scoreboard reads {finals[t['abbr'].upper()]}. "
                            "A play may be missing or misread; check the list below.")
        t['final'] = finals.get(t['abbr'].upper(), t['total'])
    return {"teams": teams, "plays": plays, "warnings": warnings}

def read_uploads(selected_model=None):
    uploads = list_uploads()
    if not uploads:
        raise ValueError("Upload the post-game screenshots first.")
    model = vision_model(selected_model)
    readings, finals, board_teams = [], {}, []
    for upload in uploads:
        base = os.path.join(UPLOAD_DIR, upload['id'])
        board = ask_image(model, base + "_full.png", BOARD_PROMPT)
        for t in board.get('teams') or []:
            if isinstance(t, dict) and t.get('abbr'):
                abbr = re.sub(r"[^A-Za-z0-9]", "", t['abbr']).upper()
                if isinstance(t.get('final'), int):
                    finals.setdefault(abbr, []).append(t['final'])
                if abbr not in [b['abbr'] for b in board_teams]:
                    board_teams.append({"abbr": abbr, "name": t.get('name') or abbr})
        plays = []
        for p in (ask_image(model, base + "_summary.png", PLAYS_PROMPT).get('plays') or []):
            if not isinstance(p, dict) or not p.get('text'):
                continue
            text = re.sub(r",?\s*\d+:\d\d\s*$", "", p['text']).strip().rstrip(",")
            clock = p.get('clock') or (re.search(r"(\d+:\d\d)\s*$", p['text']) or [None, None])[1]
            quarter = p['quarter'] if isinstance(p.get('quarter'), int) else QUARTER_WORDS.get(str(p.get('quarter')).split()[0].lower(), 1)
            plays.append({"quarter": quarter, "team": re.sub(r"[^A-Za-z0-9]", "", p.get('team') or "").upper(), "text": text, "clock": clock or ""})
        readings.append(plays)
    # The most common final per team across screenshots
    final_by_team = {abbr: max(set(values), key=values.count) for abbr, values in finals.items()}
    teams = []
    for b in board_teams[:2]:
        row = match_team(b['abbr'], b['name'])
        teams.append({"abbr": b['abbr'], "name": row['name'] if row else b['name'], "team_id": row['team_id'] if row else None})
    names = roster_names([t['team_id'] for t in teams])
    plays = merge_plays(readings)
    for p in plays:
        p['text'] = fix_names(p['text'], names)
    draft = build_draft(teams, plays, final_by_team)
    save_draft(draft)
    return draft

def save_draft(draft):
    conn = database.get_db_connection()
    conn.execute("INSERT OR REPLACE INTO event_draft (draft_id, draft_json) VALUES (1, ?)", (json.dumps(draft),))
    conn.commit()
    conn.close()

def query_draft():
    conn = database.get_db_connection()
    row = conn.execute("SELECT draft_json FROM event_draft WHERE draft_id = 1").fetchone()
    conn.close()
    return json.loads(row['draft_json']) if row else None

def clear_draft():
    conn = database.get_db_connection()
    conn.execute("DELETE FROM event_draft")
    conn.commit()
    conn.close()

# ---------- Scoring summaries from the save ----------

def clock_text(seconds):
    seconds = max(0, int(seconds or 0))
    return f"{seconds // 60}:{seconds % 60:02d}"

def risen_players(earlier, later, side):
    """The team's featured players whose touchdown count went up between two snapshots."""
    before = {s['playerId']: s['touchdowns'] for s in (earlier or {}).get(side, [])}
    return [s for s in (later or {}).get(side, []) if s['touchdowns'] > before.get(s['playerId'], 0)]

def scorer_text(row, previous, side, points, next_other=None):
    """Who scored, from the featured players' touchdown counts going up since that team's previous score.
    The snapshot slots are the team's passer, rusher and receiver; a scorer outside those three can't be named.
    About a fifth of the time the snapshot lags a score; then the other team's next score shows the rise."""
    if points in (3,):
        return "Field goal"
    if points == 2:
        return "Safety"
    risen = risen_players(previous, row, side) or (risen_players(row, next_other, side) if next_other else [])
    passer = next((s for s in risen if s['position'] == 'QB' and s['attempts']), None)
    scorer = next((s for s in risen if s is not passer), None)
    extra = {7: " (kick)", 8: " (two-point conversion)", 6: " (kick failed)"}.get(points, "")
    if scorer and passer:
        return f"{scorer['name']} touchdown catch from {passer['name']}{extra}"
    if scorer:
        kind = "catch" if scorer['position'] in ('WR', 'TE') else "run"
        return f"{scorer['name']} touchdown {kind}{extra}"
    if passer:
        return f"Touchdown pass from {passer['name']}{extra}"
    return f"Touchdown{extra}"

# A player's whole-game touchdowns by kind, from his stat line
TOUCHDOWN_STATS = {"RUSHTDS": "run", "RECEIVETDS": "catch", "DSECINTTDS": "interception return", "DLINEFUMBLETDS": "fumble return",
                   "KRETTDS": "kickoff return", "PRETTDS": "punt return"}

def game_touchdowns(game_id, team_id):
    """{(player name, kind): count} for one team in one game. The save writes a week's stat lines when the week
    advances, so this is empty for the newest week's games until then."""
    players = league.query_players()
    counts = {}
    for row in league.query_rows("SELECT player_id, stats_json FROM league_player_games WHERE game_id = ?", (game_id,)):
        player = players.get(row['player_id'])
        if not player or player['team_id'] != team_id:
            continue
        stats = json.loads(row['stats_json'] or "{}")
        for stat, kind in TOUCHDOWN_STATS.items():
            if stats.get(stat):
                counts[(player['name'], kind)] = counts.get((player['name'], kind), 0) + stats[stat]
    return counts

def scored_kind(parsed):
    return {"pass": "catch", "run": "run"}.get(parsed['kind'], parsed['kind'])

def name_remaining_scorers(plays, touchdowns):
    """Names the touchdowns the snapshots couldn't, from the game's stat lines. The scores already named are taken out
    first; a play is then named only when exactly one player is left who could have scored it (never a guess)."""
    left = dict(touchdowns)
    unnamed = []
    for p in plays:
        parsed = parse_play(p['text'])
        if parsed['points'] < 6:
            continue
        if not parsed['player']:
            unnamed.append((p, parsed))
            continue
        # A named scorer uses up one of his touchdowns (of the named kind if he has one, otherwise any)
        mine = [key for key in left if key[0] == parsed['player'] and left[key] > 0]
        key = next((k for k in mine if k[1] == scored_kind(parsed)), mine[0] if mine else None)
        if key:
            left[key] -= 1
    pending_passes = sum(1 for _, parsed in unnamed if parsed['passer'])
    for p, parsed in unnamed:
        # "Touchdown pass from X" was a catch; a plain "Touchdown" could be anything, except a catch when every catch
        # left is already spoken for by an unnamed "pass from" play
        catches_left = sum(count for key, count in left.items() if key[1] == "catch")
        no_catch = not parsed['passer'] and catches_left <= pending_passes
        candidates = [key for key, count in left.items() if count > 0 and
                      (key[1] == "catch" if parsed['passer'] else not (no_catch and key[1] == "catch"))]
        if len(candidates) != 1:
            continue
        name, kind = candidates[0]
        left[(name, kind)] -= 1
        if parsed['passer']:
            pending_passes -= 1
        extra = re.search(r"\s*\([^)]*\)$", p['text'])
        extra = extra.group(0) if extra else ""
        if kind == "catch":
            p['text'] = f"{name} touchdown catch" + (f" from {parsed['passer']}" if parsed['passer'] else "") + extra
        elif kind == "run":
            p['text'] = f"{name} touchdown run{extra}"
        else:
            p['text'] = f"{name} {kind} touchdown{extra}"
    return plays

def draft_from_save(game_id):
    """A review draft (same shape as the screenshot reading) built from a scoring summary captured from the save,
    stored as the podcast's current draft."""
    draft = build_save_draft(game_id)
    save_draft(draft)
    return draft

def build_save_draft(game_id):
    """The scoring plays of a game captured from the save, with per-quarter totals; ValueError if none were captured."""
    plays = league.query_game_scoring(game_id)
    # The pool also logs moments where neither score changed (ends of halves, failed tries); only real scores count
    plays = [p for p in plays or [] if p['homeAfter'] > p['homeBefore'] or p['awayAfter'] > p['awayBefore']]
    game = next((g for g in league.query_rows("SELECT * FROM league_games WHERE game_id = ?", (game_id,))), None)
    if not plays or not game:
        raise ValueError("That game's scoring summary isn't saved.")
    teams = league.query_teams()
    home, away = teams[game['home_id']], teams[game['away_id']]
    abbr = {game['home_id']: home['short_name'] or home['name'][:4].upper(), game['away_id']: away['short_name'] or away['name'][:4].upper()}
    finals = {'home': game['home_score'], 'away': game['away_score']}
    out, previous = [], {'home': None, 'away': None}
    for index, row in enumerate(plays):
        side = 'home' if row['homeAfter'] > row['homeBefore'] else 'away'
        later = next((p for p in plays[index + 1:]), None)
        # The extra point lands in the next score's "before" (or the final), not in this row
        points = (later[f'{side}Before'] if later else finals[side]) - row[f'{side}Before']
        team_id = game['home_id'] if side == 'home' else game['away_id']
        # Only borrow the next row's rise when the other team scored next (a same-team rise could be its next touchdown)
        next_other = later if later and (later['homeAfter'] > later['homeBefore']) != (side == 'home') else None
        out.append({"quarter": min(row['quarter'], 5), "team": abbr[team_id], "text": scorer_text(row, previous[side], side, points, next_other),
                    "clock": clock_text(row['secondsLeft'])})
        previous[side] = row
    for team_id in (game['home_id'], game['away_id']):
        name_remaining_scorers([p for p in out if p['team'] == abbr[team_id]], game_touchdowns(game_id, team_id))
    draft_teams = [{"abbr": abbr[t['team_id']], "name": t['name'], "team_id": t['team_id']} for t in (away, home)]
    draft = build_draft(draft_teams, out, {abbr[game['away_id']].upper(): game['away_score'], abbr[game['home_id']].upper(): game['home_score']})
    return draft

def saved_games():
    """Games with a captured scoring summary for the picker: ours first, newest week first."""
    teams = league.query_teams()
    user = next((tid for tid, t in teams.items() if t.get('is_user')), None)
    games = league.query_scoring_games()
    games.sort(key=lambda g: (user not in (g['home_id'], g['away_id']), -g['week']))
    return [{"game_id": g['game_id'], "week": g['week'], "ours": user in (g['home_id'], g['away_id']),
             "label": f"Week {g['week']}: {teams[g['away_id']]['name']} {g['away_score']} at {teams[g['home_id']]['name']} {g['home_score']}"}
            for g in games if g['home_id'] in teams and g['away_id'] in teams]

# Auto-initialize when events.py gets imported
initialize_event_tables()
