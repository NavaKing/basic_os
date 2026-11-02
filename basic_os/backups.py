import contextlib
import datetime
import gzip
import os
import re
import shutil
import sqlite3
import tempfile
import database

# Copies of dynasty_data.db: made by hand from the Backups window, or automatically right before a save sync
# writes new data. Copies use SQLite's backup API, so they're consistent even while the app is running, and are
# stored gzip-compressed (about a quarter of the size). Older uncompressed .db backups still list, restore and download.
# Restoring brings back everything the app made (stories, storylines, podcasts, quotes, game plans, edits);
# schedule and stats re-sync from the dynasty save on the next page load as usual.

BACKUP_DIR = os.environ.get("BASIC_OS_BACKUPS") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")
AUTO_LABEL = "before-sync"
AUTO_KEEP = 10          # automatic backups kept; hand-made ones are only deleted by hand
FILE_PATTERN = re.compile(r"^dynasty_(\d{8}-\d{6})(?:_([a-z0-9-]{1,40}))?\.db(\.gz)?$")
REQUIRED_TABLES = {"schedule_tracking", "team_roster"}  # what makes a file a BASIC_OS database
LABEL_TEXT = {AUTO_LABEL: "Automatic, before a save sync", "before-restore": "Automatic, before a restore", "uploaded": "Uploaded"}
SQLITE_HEADER = b"SQLite format 3\x00"
GZIP_MAGIC = b"\x1f\x8b"

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

def compress(source, target):
    with open(source, "rb") as src, gzip.open(target, "wb", compresslevel=6) as dst:
        shutil.copyfileobj(src, dst)

@contextlib.contextmanager
def plain_copy(path):
    """Yields the path of an uncompressed copy of a backup (the file itself when it isn't compressed)."""
    if not path.endswith(".gz"):
        yield path
        return
    folder = tempfile.mkdtemp(prefix="basic_os_backup_")
    try:
        plain = os.path.join(folder, "dynasty.db")
        with gzip.open(path, "rb") as src, open(plain, "wb") as dst:
            shutil.copyfileobj(src, dst)
        yield plain
    finally:
        shutil.rmtree(folder, ignore_errors=True)

def new_name(label):
    """A fresh backup file name; ValueError if one was made in this same second."""
    name = f"dynasty_{timestamp()}{'_' + label if label else ''}.db.gz"
    if os.path.exists(os.path.join(BACKUP_DIR, name)) or os.path.exists(os.path.join(BACKUP_DIR, name[:-3])):
        raise ValueError("A backup was just made; try again in a moment.")
    return name

def store(plain_db, label):
    """Compresses an uncompressed database into the backups folder; returns the new file name."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    name = new_name(label)
    compress(plain_db, os.path.join(BACKUP_DIR, name))
    return name

def create_backup(label=""):
    label = clean_label(label)
    folder = tempfile.mkdtemp(prefix="basic_os_backup_")
    try:
        snapshot = os.path.join(folder, "dynasty.db")
        copy_database(database.DB_FILE, snapshot)
        name = store(snapshot, label)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if label == AUTO_LABEL:
        prune_automatic()
    return name

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
    """ValueError unless the (uncompressed) file is an intact BASIC_OS database."""
    with open(path, "rb") as f:
        if f.read(16) != SQLITE_HEADER:
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
    with plain_copy(backup_path(file_name)) as plain:
        check_database(plain)
        safety = create_backup("before-restore")
        copy_database(plain, database.DB_FILE)
    return safety

def download(file_name):
    """(bytes, file name) of a backup as a plain .db file, ready to upload on another PC."""
    with plain_copy(backup_path(file_name)) as plain:
        with open(plain, "rb") as f:
            return f.read(), re.sub(r"\.gz$", "", file_name)

def delete_backup(file_name):
    os.remove(backup_path(file_name))

def save_upload(data):
    """Stores an uploaded database (plain or gzip-compressed) as a backup; it can then be restored like any other."""
    folder = tempfile.mkdtemp(prefix="basic_os_upload_")
    try:
        plain = os.path.join(folder, "upload.db")
        if data[:2] == GZIP_MAGIC:
            try:
                data = gzip.decompress(data)
            except OSError as e:
                raise ValueError("That compressed file is damaged.") from e
        with open(plain, "wb") as f:
            f.write(data)
        check_database(plain)
        return store(plain, "uploaded")
    finally:
        shutil.rmtree(folder, ignore_errors=True)

def compress_old_backups():
    """Uncompressed .db backups from before compression -> .db.gz (housekeeping). Returns how many."""
    count = 0
    for b in list_backups():
        if b['file'].endswith(".db"):
            path = os.path.join(BACKUP_DIR, b['file'])
            compress(path, path + ".gz")
            os.remove(path)
            count += 1
    return count
