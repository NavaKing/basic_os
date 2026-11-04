"""Which dynasty the app is following. Every time the app opens it asks which save to load (the last one is
preselected); each save gets its own app database, so stories, care, the group chat and history never mix between
dynasties. DYNASTY-WYOYEAR1 keeps the original dynasty_data.db and backups folder; any other save gets
dynasties/<save>.db and backups/dynasties/<save>/ the first time it's picked.

Tests (and anyone setting BASIC_OS_DB or DYNASTY_SAVE_FILE) get a fixed dynasty and no chooser."""
import datetime
import importlib
import json
import os
import sqlite3

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SAVES_DIR = os.path.join(os.path.expanduser("~"), "Documents", "EA SPORTS College Football 27", "saves")
REGISTRY = os.path.join(APP_DIR, "dynasties.json")
ORIGINAL = "DYNASTY-WYOYEAR1"   # the dynasty the app was built around: its data stays where it always was
FIXED = bool(os.environ.get("BASIC_OS_DB") or os.environ.get("DYNASTY_SAVE_FILE"))

# Every module that creates its tables when imported; a switch re-runs them against the new database
TABLE_SETUP = [("database", "initialize_database_tables"), ("roster", "initialize_roster_table"), ("league", "initialize_league_tables"),
               ("save_sync", "initialize_sync_table"), ("history", "initialize_history_tables"), ("awards", "initialize_awards_tables"),
               ("coaches", "initialize_coach_tables"), ("events", "initialize_event_tables"), ("gameplan", "initialize_gameplan_tables"),
               ("offseason", "initialize_offseason_tables"), ("podcast", "initialize_podcast_tables"), ("presser", "initialize_presser_tables"),
               ("recruiting", "initialize_recruiting_tables"), ("rivals", "initialize_rival_tables"), ("scouting", "initialize_scouting_table"),
               ("storylines", "initialize_storyline_tables"), ("care", "initialize_care_tables"), ("care_messages", "initialize_tables"),
               ("care_incidents", "initialize_tables"), ("team_board", "initialize_tables"), ("group_chat", "initialize_tables"),
               ("game_day", "initialize_tables"), ("career", "initialize_tables")]

state = {"current": None, "chosen": FIXED}

def registry():
    try:
        with open(REGISTRY, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}

def save_registry(data):
    with open(REGISTRY, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def db_path(name):
    if name == ORIGINAL:
        return os.path.join(APP_DIR, "dynasty_data.db")
    return os.path.join(APP_DIR, "dynasties", f"{name}.db")

def backup_dir(name):
    if name == ORIGINAL:
        return os.path.join(APP_DIR, "backups")
    return os.path.join(APP_DIR, "backups", "dynasties", name)

def describe(path):
    """(team, status line) from a dynasty's app database, or (None, None) when it has none yet."""
    if not os.path.exists(path):
        return None, None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        team = conn.execute("SELECT name, nickname FROM league_teams WHERE is_user = 1").fetchone()
        status = conn.execute("SELECT state_value FROM sync_state WHERE state_key = 'status'").fetchone()
        conn.close()
        return (f"{team[0]} {team[1] or ''}".strip() if team else None), (status[0] if status else None)
    except sqlite3.Error:
        return None, None

def saves():
    """Every dynasty save in the game's saves folder, most recently played first (an autosave counts toward its save)."""
    if not os.path.isdir(SAVES_DIR):
        return []
    out = []
    for name in os.listdir(SAVES_DIR):
        path = os.path.join(SAVES_DIR, name)
        if not name.startswith("DYNASTY-") or name.endswith("-AUTOSAVE") or not os.path.isfile(path):   # not Road to Glory, rosters or Team Builder
            continue
        played = max(os.path.getmtime(p) for p in (path, path + "-AUTOSAVE") if os.path.exists(p))
        team, status = describe(db_path(name))
        out.append({"name": name, "label": name.replace("DYNASTY-", "", 1), "played": datetime.datetime.fromtimestamp(played).strftime("%b %d, %Y %I:%M %p").replace(" 0", " "),
                    "played_at": played, "team": team, "status": status, "has_data": team is not None})
    return sorted(out, key=lambda s: -s['played_at'])

def busy():
    """A background job writing into the current dynasty (a chat being written, texts being voiced)."""
    import care_messages
    import group_chat
    import save_sync
    return bool(care_messages._voicing.get('running') or save_sync._sync_lock.locked()
                or any(j and not j.get('done') for j in group_chat._jobs.values()))

def switch(name):
    """Points the whole app at another dynasty: its save, its own database and backups. Raises ValueError."""
    path = os.path.join(SAVES_DIR, name)
    if os.path.basename(name) != name or not name.startswith("DYNASTY-") or name.endswith("-AUTOSAVE") or not os.path.isfile(path):
        raise ValueError("That save isn't in the College Football 27 saves folder.")
    if state['current'] not in (None, name) and busy():
        raise ValueError("The app is still writing messages for the current dynasty. Give it a minute, then switch.")
    import backups
    import database
    import game_day
    import roster
    import save_sync
    os.makedirs(os.path.dirname(db_path(name)), exist_ok=True)
    database.DB_FILE = roster.DB_FILE = db_path(name)
    save_sync.SAVE_FILE = path
    backups.BACKUP_DIR = backup_dir(name)
    game_day.SAVE_BACKUPS = os.path.join(backup_dir(name), "saves")
    for module, setup in TABLE_SETUP:
        getattr(importlib.import_module(module), setup)()
    state.update(current=name, chosen=True)
    save_registry({**registry(), "last": name})
    return current()

def current():
    import save_sync
    name = state['current'] or os.path.basename(save_sync.SAVE_FILE)
    team, status = describe(db_path(name)) if not FIXED else (None, None)
    return {"name": name, "label": name.replace("DYNASTY-", "", 1), "team": team, "status": status, "chosen": state['chosen'], "fixed": FIXED}

def last():
    return registry().get('last') or ORIGINAL
