"""Game-day boosts: player care reaching the game. Before each game, players the coach has cared for well start Hot with
1-3 extra mental abilities (Bronze, rolled to fit their position, never one they already have) for that game only;
neglected players start Cold. The app writes them into the dynasty save (the game must be closed), and the next time
boosts are applied (or the coach presses Remove) the previous week's are taken back out.

Safety: only Hot/Cold and the mental ability slots are written (save_reader/write_boosts.mjs refuses anything else and
verifies the file before replacing it); every write backs the save up first and can be undone; nothing is written while
College Football 27 is running, because the game would overwrite the file with its own copy."""
import datetime
import json
import os
import random
import shutil
import subprocess
import care
import database
import league
import roster
import save_sync

WRITER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "save_reader", "write_boosts.mjs")
SAVE_BACKUPS = os.environ.get("BASIC_OS_SAVE_BACKUPS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups", "saves")
GAME_PROCESS = "CollegeFB27.exe"

# Mental abilities a player can be lent. Every position can use these (Home or Road Fan Favorite depending on where
# the game is); the position groups add their own. Hot Head is left out: its effect isn't documented.
ANY_POSITION = ["ClearHeaded", "TheNatural", "WinningTime", "TeamPlayer", "Adrenaline", "Headstrong"]
BY_POSITION = {"QB": ["FieldGeneral", "BestFriend"], "HB": ["BellCow"], "K": ["ClutchKicker"],
               **{p: ["OLRally"] for p in ("LT", "LG", "C", "RG", "RT")},
               **{p: ["DLRally"] for p in ("LE", "RE", "DT")},
               **{p: ["DBRally"] for p in ("CB", "FS", "SS")}}
LABELS = {"ClearHeaded": "Clear Headed", "TheNatural": "The Natural", "WinningTime": "Winning Time", "TeamPlayer": "Team Player",
          "Adrenaline": "Adrenaline", "Headstrong": "Headstrong", "HomeFanFavorite": "Home Fan Favorite", "RoadFanFavorite": "Road Fan Favorite",
          "FieldGeneral": "Field General", "BestFriend": "Best Friend", "BellCow": "Bell Cow", "ClutchKicker": "Clutch Kicker",
          "OLRally": "OL Rally", "DLRally": "DL Rally", "DBRally": "DB Rally"}

def initialize_tables():
    conn = database.get_db_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS boost_runs (
        run_id INTEGER PRIMARY KEY AUTOINCREMENT,
        week INTEGER, applied_at TEXT, files_json TEXT,   -- [{"save": path, "backup": path}]
        status TEXT DEFAULT 'applied'                     -- applied, removed (taken back out), undone (backups restored)
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS boost_changes (
        run_id INTEGER, save_id TEXT, name TEXT, field TEXT, before TEXT, after TEXT
    )
    """)
    conn.commit()
    conn.close()

def execute(sql, params=()):
    conn = database.get_db_connection()
    cursor = conn.execute(sql, params)
    conn.commit()
    conn.close()
    return cursor.lastrowid

def tuning():
    return care.load_tuning()['game_day']

# ---------- Who earns what ----------

def tier(player, ctx, t):
    """'excellent', 'great', 'good', 'cold' or None from the player's needs (the ones that count this week) and trust."""
    worries = care.worries(player['needs'], ctx)
    lowest, trust, morale = min(worries.values()), player['trust'], player['needs']['morale']
    for name in ("excellent", "great", "good"):
        rule = t['tiers'][name]
        if lowest >= rule['lowest_need'] and trust >= rule['trust'] and morale >= rule.get('morale', 0):
            return name
    if lowest < t['cold']['lowest_need_below'] and trust < t['cold']['trust_below']:
        return "cold"
    return None

def perk_pool(position, site):
    fan = "HomeFanFavorite" if site == "Home" else "RoadFanFavorite"   # a neutral-site or road game is a road crowd
    return ANY_POSITION + [fan] + BY_POSITION.get(position, [])

def roll_perks(player, count, site, rng):
    """Up to `count` Bronze abilities he doesn't already have, into his empty slots: [(slot, ability)]."""
    owned = {m['name'] for m in player['mentals'] if m['name'] and m['name'] != "None"}
    empty = [m['slot'] for m in player['mentals'] if not m['name'] or m['name'] == "None"]
    choices = [a for a in perk_pool(player['position'], site) if a not in owned]   # rerolls past anything he has, at any tier
    rng.shuffle(choices)
    return list(zip(empty, choices))[:count]

def candidates():
    """Our players with what the boosts need: care needs and trust, position, current mental slots and Hot/Cold."""
    if care.get_state("week") is None:
        return [], {}
    week = int(care.get_state("week"))
    ctx = care.week_context(week)
    rows = {p['save_id']: p for p in roster.query_full_roster() if p.get('save_id')}
    previous = last_run()
    lent = {}   # save_id -> {slot: ability} still in the save from the last boosts
    if previous and previous['status'] == "applied":
        for r in league.query_rows("SELECT save_id, field, after FROM boost_changes WHERE run_id = ? AND field LIKE 'MentalAbility_'",
                                   (previous['run_id'],)):
            lent.setdefault(r['save_id'], {})[int(r['field'][-1])] = r['after']
    out = []
    for p in care.load_players():
        row = rows.get(p['save_id']) or {}
        mentals = json.loads(row.get('mentals_json') or "[]") or [{"slot": i, "name": "None", "rank": "None"} for i in (1, 2, 3)]
        mentals = [{**m, "name": "None", "rank": "None"} if lent.get(p['save_id'], {}).get(m['slot']) == m['name'] else m for m in mentals]
        out.append({**p, "mentals": mentals, "hot_cold": row.get('hot_cold'), "injured": p['injured']})
    return out, ctx

def plan(seed=None):
    """This week's boosts: [{save_id, name, position, tier, hot_cold, perks: [(slot, ability)]}], best cared-for first,
    capped at max_hot Hot and max_cold Cold players. Injured players aren't boosted."""
    t = tuning()
    players, ctx = candidates()
    if not players:
        return {"week": None, "players": [], "site": None}
    week = int(care.get_state("week"))
    game = database.query_active_week() or {}
    site = game.get('site')
    rng = random.Random(seed if seed is not None else f"boosts-{care.season_seed()}-{week}")
    count = {"excellent": 3, "great": 2, "good": 1}
    rank = {"excellent": 0, "great": 1, "good": 2}
    hot = [(tier(p, ctx, t), p) for p in players if not p['injured']]
    hot = sorted([(name, p) for name, p in hot if name in count],
                 key=lambda x: (rank[x[0]], not x[1]['starter'], -x[1]['trust']))[:t['max_hot']]
    cold = sorted([p for p in players if tier(p, ctx, t) == "cold"], key=lambda p: (p['trust'], min(p['needs'].values())))[:t['max_cold']]
    out = [{"save_id": p['save_id'], "name": p['name'], "position": p['position'], "tier": name, "hot_cold": "Hot",
            "perks": roll_perks(p, count[name], site, rng)} for name, p in hot]
    out += [{"save_id": p['save_id'], "name": p['name'], "position": p['position'], "tier": "cold", "hot_cold": "Cold", "perks": []}
            for p in cold]
    return {"week": week, "players": out, "site": site, "opponent": game.get('opponent_name')}

# ---------- Writing to the save ----------

def game_running():
    """True when College Football 27 is open (it would overwrite the save with its own copy)."""
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {GAME_PROCESS}", "/NH"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return GAME_PROCESS.lower() in out.lower()

def save_files():
    """The dynasty save and its autosave (both are written, so whichever the game loads has the same boosts)."""
    return [p for p in (save_sync.SAVE_FILE, save_sync.SAVE_FILE + "-AUTOSAVE") if os.path.exists(p)]

def write(save_path, changes):
    """Runs the writer on one save file; returns {row: {field: value before}}. Raises RuntimeError if it fails."""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(changes, f)
        path = f.name
    try:
        result = subprocess.run([save_sync.NODE_EXE, WRITER, save_path, path], capture_output=True, text=True, encoding="utf-8", timeout=180)
    finally:
        os.remove(path)
    if result.returncode != 0:
        lines = [line.strip() for line in result.stderr.splitlines() if "Error" in line]
        raise RuntimeError(lines[0] if lines else f"the save writer exited with code {result.returncode}")
    return {int(k): v for k, v in json.loads(result.stdout.strip().splitlines()[-1])['before'].items()}

def last_run():
    rows = league.query_rows("SELECT * FROM boost_runs ORDER BY run_id DESC LIMIT 1")
    return rows[0] if rows else None

def take_back(run):
    """Changes that put a run's boosts back the way the save had them, for fields that still hold what we wrote (if the
    game changed one since, e.g. re-rolled Hot/Cold, it's left alone)."""
    rows = league.query_rows("SELECT * FROM boost_changes WHERE run_id = ?", (run['run_id'],))
    by_player = {}
    for r in rows:
        by_player.setdefault(r['save_id'], {})[r['field']] = (r['before'], r['after'])
    return by_player

def check_ready():
    if game_running():
        raise ValueError("Close College Football 27 first: while it's open it would overwrite the save with its own copy.")
    if not save_files():
        raise ValueError("The dynasty save wasn't found.")

def backup_saves(week):
    os.makedirs(SAVE_BACKUPS, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    files = []
    for path in save_files():
        backup = os.path.join(SAVE_BACKUPS, f"{os.path.basename(path)}.week{week}.{stamp}")
        shutil.copy2(path, backup)
        files.append({"save": path, "backup": backup})
    return files

def apply(seed=None):
    """Takes last week's boosts back out and writes this week's (one backup, one write per save file)."""
    check_ready()
    proposal = plan(seed)
    if proposal['week'] is None:
        raise ValueError("Player care hasn't started yet.")
    previous = last_run()
    restore = take_back(previous) if previous and previous['status'] == "applied" else {}
    files = backup_saves(proposal['week'])
    wanted = {}   # save_id -> {field: value}
    for save_id, fields in restore.items():
        for field, (before, after) in fields.items():
            wanted.setdefault(save_id, {})[field] = (before, after)   # restore only if it still reads `after`
    new = {}
    for p in proposal['players']:
        fields = {"StartingHotCold": p['hot_cold']}
        for slot, ability in p['perks']:
            fields[f"MentalAbility{slot}"] = ability
            fields[f"MentalAbilityRank{slot}"] = "Bronze"
        new[p['save_id']] = fields
    names = {p['save_id']: p['name'] for p in proposal['players']}
    run_id = execute("INSERT INTO boost_runs (week, applied_at, files_json) VALUES (?, ?, ?)",
                     (proposal['week'], datetime.datetime.now().isoformat(timespec="seconds"), json.dumps(files)))
    try:
        for f in files:
            changes = []
            for save_id in set(wanted) | set(new):
                fields = {field: before for field, (before, _) in wanted.get(save_id, {}).items()}
                only_if = {field: after for field, (_, after) in wanted.get(save_id, {}).items() if field not in new.get(save_id, {})}
                fields.update(new.get(save_id, {}))
                changes.append({"row": int(save_id.split(":")[1]), "set": fields, **({"onlyIf": only_if} if only_if else {})})
            before = write(f['save'], changes)
            if f is files[0]:
                for save_id, fields in new.items():
                    row = int(save_id.split(":")[1])
                    for field, value in fields.items():
                        original = wanted.get(save_id, {}).get(field, (before[row].get(field), None))[0]
                        execute("INSERT INTO boost_changes (run_id, save_id, name, field, before, after) VALUES (?, ?, ?, ?, ?, ?)",
                                (run_id, save_id, names[save_id], field, original, value))
    except Exception:
        restore_files(files)   # all or nothing: put every save file back as it was
        execute("UPDATE boost_runs SET status = 'undone' WHERE run_id = ?", (run_id,))
        raise
    if previous and previous['status'] == "applied":
        execute("UPDATE boost_runs SET status = 'removed' WHERE run_id = ?", (previous['run_id'],))
    care.log(proposal['week'], None, "game_day", summary(proposal))
    return status()

def remove():
    """Takes the last boosts back out of the save without adding new ones."""
    check_ready()
    run = last_run()
    if not run or run['status'] != "applied":
        raise ValueError("There are no boosts in the save to remove.")
    restore = take_back(run)
    backup_saves(run['week'])
    for f in save_files():
        write(f, [{"row": int(save_id.split(":")[1]), "set": {field: before for field, (before, _) in fields.items()},
                   "onlyIf": {field: after for field, (_, after) in fields.items()}} for save_id, fields in restore.items()])
    execute("UPDATE boost_runs SET status = 'removed' WHERE run_id = ?", (run['run_id'],))
    care.log(run['week'], None, "game_day", "Game-day boosts taken back out of the save.")
    return status()

def restore_files(files):
    for f in files:
        if os.path.exists(f['backup']):
            shutil.copy2(f['backup'], f['save'])

def undo():
    """Puts the save files back exactly as they were before the last write."""
    check_ready()
    run = last_run()
    if not run or run['status'] != "applied":
        raise ValueError("Nothing to undo.")
    restore_files(json.loads(run['files_json']))
    execute("UPDATE boost_runs SET status = 'undone' WHERE run_id = ?", (run['run_id'],))
    care.log(run['week'], None, "game_day", "Last game-day write undone: the save is back as it was.")
    return status()

def summary(proposal):
    hot = [p for p in proposal['players'] if p['hot_cold'] == "Hot"]
    cold = [p for p in proposal['players'] if p['hot_cold'] == "Cold"]
    lines = [f"{p['name']} ({', '.join(LABELS[a] for _, a in p['perks'])})" if p['perks'] else p['name'] for p in hot]
    return (f"Game-day boosts written to the save: {len(hot)} start Hot" + (f": {'; '.join(lines)}" if lines else "") +
            (f". {len(cold)} start Cold: {', '.join(p['name'] for p in cold)}" if cold else "") + ". Bronze, for this game only.")

def status():
    """For the Care app: this week's proposal, the last write, and whether the game is open."""
    proposal = plan()
    run = last_run()
    week = proposal['week']
    shaped = [{**p, "perks": [{"slot": s, "ability": LABELS[a]} for s, a in p['perks']]} for p in proposal['players']]
    return {"week": week, "site": proposal.get('site'), "opponent": proposal.get('opponent'), "players": shaped,
            "game_running": game_running(), "save_found": bool(save_files()),
            "last": {"week": run['week'], "status": run['status'], "applied_at": run['applied_at'],
                     "stale": run['status'] == "applied" and week is not None and run['week'] < week,
                     "players": len({r['save_id'] for r in league.query_rows("SELECT save_id FROM boost_changes WHERE run_id = ?", (run['run_id'],))})}
            if run else None}

initialize_tables()
