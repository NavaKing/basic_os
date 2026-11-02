import datetime
import os
import re
import sqlite3
import database

# Copies of dynasty_data.db: made by hand from the Backups window, or automatically right before a save sync
# writes new data. Copies use SQLite's backup API, so they're consistent even while the app is running.
# Restoring brings back everything the app made (stories, storylines, podcasts, quotes, game plans, edits);
# schedule and stats re-sync from the dynasty save on the next page load as usual.

BACKUP_DIR = os.environ.get("BASIC_OS_BACKUPS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")
AUTO_LABEL = "before-sync"
AUTO_KEEP = 10          # automatic backups kept; hand-made ones are only deleted by hand
FILE_PATTERN = re.compile(r"^dynasty_(\d{8}-\d{6})(?:_([a-z0-9-]{1,40}))?\.db$")
REQUIRED_TABLES = {"schedule_tracking", "team_roster"}  # what makes a file a BASIC_OS database
LABEL_TEXT = {AUTO_LABEL: "Automatic, before a save sync", "before-restore": "Automatic, before a restore", "uploaded": "Uploaded"}

def timestamp():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

def clean_label(label):
    return re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")[:40]

def backup_path(file_name):
    """The full path of a backup, or ValueError for anything that isn't one (no paths, no other files)."""
    if not FILE_PATTERN.match(file_name or ""):
        raise ValueError("That isn't a backup file.")
    path = os.path.join(BACKUP_DIR, file_name)
    if not os.path.exists(path):
        raise ValueError("That backup no longer exists.")
    return path

def copy_database(source, target):
    src, dst = sqlite3.connect(source), sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()

def create_backup(label=""):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    label = clean_label(label)
    stamp = timestamp()
    file_name = f"dynasty_{stamp}{'_' + label if label else ''}.db"
    path = os.path.join(BACKUP_DIR, file_name)
    if os.path.exists(path):  # two in the same second
        raise ValueError("A backup was just made; try again in a moment.")
    copy_database(database.DB_FILE, path)
    if label == AUTO_LABEL:
        prune_automatic()
    return file_name

def list_backups():
    """Newest first: [{file, created (ISO), label, label_text, size, automatic}]."""
    if not os.path.isdir(BACKUP_DIR):
        return []
    out = []
    for file_name in os.listdir(BACKUP_DIR):
        match = FILE_PATTERN.match(file_name)
        if not match:
            continue
        label = match.group(2) or ""
        created = datetime.datetime.strptime(match.group(1), "%Y%m%d-%H%M%S")
        out.append({"file": file_name, "created": created.isoformat(timespec="minutes"), "label": label,
                    "label_text": LABEL_TEXT.get(label, label.replace("-", " ").capitalize() or "Backup"),
                    "size": os.path.getsize(os.path.join(BACKUP_DIR, file_name)),
                    "automatic": label in (AUTO_LABEL, "before-restore")})
    return sorted(out, key=lambda b: b['file'], reverse=True)

def prune_automatic():
    for b in [b for b in list_backups() if b['label'] == AUTO_LABEL][AUTO_KEEP:]:
        os.remove(os.path.join(BACKUP_DIR, b['file']))

def check_database(path):
    """ValueError unless the file is an intact BASIC_OS database."""
    with open(path, "rb") as f:
        if f.read(16) != b"SQLite format 3\x00":
            raise ValueError("That file isn't a database.")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("That database is damaged.")
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()
    if not REQUIRED_TABLES <= tables:
        raise ValueError("That database isn't from BASIC_OS.")

def restore_backup(file_name):
    """Replaces the live database with a backup, after saving the current one as 'before-restore'."""
    path = backup_path(file_name)
    check_database(path)
    safety = create_backup("before-restore")
    copy_database(path, database.DB_FILE)
    return safety

def delete_backup(file_name):
    os.remove(backup_path(file_name))

def save_upload(data):
    """Stores an uploaded database file as a backup (it can then be restored like any other)."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = timestamp()
    path = os.path.join(BACKUP_DIR, f"dynasty_{stamp}_uploaded.db")
    with open(path, "wb") as f:
        f.write(data)
    try:
        check_database(path)
    except Exception:
        os.remove(path)
        raise
    return os.path.basename(path)
