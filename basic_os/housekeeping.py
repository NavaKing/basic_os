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

def run():
    """All upkeep steps; returns {step: count} for the ones that did something."""
    import podcast  # also makes sure every table the steps update exists
    import backups
    done = {"photos converted to WebP": convert_photos(), "backups compressed": backups.compress_old_backups(),
            "duplicate podcast MP3s removed": podcast.drop_joined_copies(), "logos shrunk": shrink_logos()}
    return {step: count for step, count in done.items() if count}
