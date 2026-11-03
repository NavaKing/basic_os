import glob
import os
import database

# Space-saving upkeep, run when the app starts. Every step is safe to repeat: it only touches files still in the old,
# larger form, so after the first run each start costs a few directory listings.

def convert_photos():
    """Generated PNGs -> WebP, updating every record that points at them. Returns how many were converted."""
    try:
        from PIL import Image
    except ImportError:
        return 0
    import image_engine
    folder = os.path.join(database.STATIC_DIR, image_engine.GENERATED_SUBDIR)
    converted = 0
    for path in glob.glob(os.path.join(folder, "*.png")):
        stem = os.path.splitext(path)[0]
        Image.open(path).convert("RGB").save(stem + ".webp", "WEBP", quality=image_engine.WEBP_QUALITY, method=6)
        old = f"{image_engine.GENERATED_SUBDIR}/{os.path.basename(path)}"
        new = old[:-len(".png")] + ".webp"
        conn = database.get_db_connection()
        for table, column in (("historical_stories", "image_path"), ("historical_tweets", "image_path"), ("podcast_episodes", "cover_image")):
            conn.execute(f"UPDATE {table} SET {column} = ? WHERE {column} = ?", (new, old))
        conn.commit()
        conn.close()
        os.remove(path)
        converted += 1
    return converted

def shrink_logos():
    import media
    return sum(media.shrink_logo(path) for path in glob.glob(os.path.join(media.LOGO_DIR, "*.png")))

def compact_scoring():
    """Rewrites scoring summaries stored before compaction (and fills in their two teams). Returns how many."""
    import json
    import league
    conn = database.get_db_connection()
    rows = conn.execute("""SELECT s.game_id, s.plays_json, g.home_id, g.away_id FROM game_scoring s
                           LEFT JOIN league_games g ON g.game_id = s.game_id
                           WHERE s.home_id IS NULL OR s.plays_json LIKE '%"catches"%'""").fetchall()
    for r in rows:
        conn.execute("UPDATE game_scoring SET plays_json = ?, home_id = COALESCE(home_id, ?), away_id = COALESCE(away_id, ?) WHERE game_id = ?",
                     (json.dumps(league.compact_plays(json.loads(r['plays_json']))), r['home_id'], r['away_id'], r['game_id']))
    conn.commit()
    conn.close()
    return len(rows)

VACUUM_FREE_BYTES = 1024 * 1024

def vacuum():
    """Gives free space inside the database back to the disk (SQLite keeps it after rows shrink or go) once it's
    over a megabyte. Returns the megabytes reclaimed (rounded), 0 when not worth it."""
    conn = database.get_db_connection()
    try:
        free = conn.execute("PRAGMA freelist_count").fetchone()[0] * conn.execute("PRAGMA page_size").fetchone()[0]
        if free < VACUUM_FREE_BYTES:
            return 0
        conn.execute("VACUUM")
        return round(free / (1024 * 1024))
    finally:
        conn.close()

def run():
    """All upkeep steps; returns {step: count} for the ones that did something."""
    import podcast  # also makes sure every table the steps update exists
    import backups
    done = {"photos converted to WebP": convert_photos(), "backups compressed": backups.compress_old_backups(),
            "duplicate podcast MP3s removed": podcast.drop_joined_copies(), "logos shrunk": shrink_logos(),
            "scoring summaries compacted": compact_scoring()}
    done["MB returned to the disk from the database"] = vacuum()  # last, after the steps that shrink rows
    return {step: count for step, count in done.items() if count}
