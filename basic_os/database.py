import os
import sqlite3
import random

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dynasty_data.db")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# Columns added to schedule_tracking after the first version (scores, then game-day details from the save)
SCHEDULE_EXTRA_COLUMNS = [
    ("wyo_score", "INTEGER"), ("opp_score", "INTEGER"),
    ("site", "TEXT"), ("game_date", "TEXT"), ("kickoff_minutes", "INTEGER"), ("network", "TEXT"),
    ("weather", "TEXT"), ("temperature", "INTEGER"), ("precip_chance", "INTEGER"), ("wind", "TEXT"), ("wind_speed", "INTEGER")
]

def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_database_tables():
    """Automatically verifies and builds missing tables on startup to prevent OperationalErrors."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Verify Schedule Tracking
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS schedule_tracking (
        week_id INTEGER PRIMARY KEY,
        opponent_name TEXT NOT NULL,
        is_played INTEGER DEFAULT 0,
        wyo_rush_yds INTEGER DEFAULT 0,
        wyo_pass_yds INTEGER DEFAULT 0,
        opp_rush_yds INTEGER DEFAULT 0,
        opp_pass_yds INTEGER DEFAULT 0,
        game_mvp TEXT DEFAULT 'TBD',
        wyo_score INTEGER,
        opp_score INTEGER
    )
    """)

    # Add score and game-day columns to databases created before they were tracked
    existing_cols = [col[1] for col in cursor.execute("PRAGMA table_info(schedule_tracking)").fetchall()]
    for col, col_type in SCHEDULE_EXTRA_COLUMNS:
        if col not in existing_cols:
            cursor.execute(f"ALTER TABLE schedule_tracking ADD COLUMN {col} {col_type}")

    # 2. Verify Historical Stories
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS historical_stories (
        story_id INTEGER PRIMARY KEY AUTOINCREMENT,
        week_num INTEGER UNIQUE,
        opponent_name TEXT NOT NULL,
        generated_text TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        image_path TEXT -- hero banner photo, relative to static/
    )
    """)
    story_cols = [col[1] for col in cursor.execute("PRAGMA table_info(historical_stories)").fetchall()]
    if "image_path" not in story_cols:
        cursor.execute("ALTER TABLE historical_stories ADD COLUMN image_path TEXT")
    
    # 3. Verify Historical Tweets
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS historical_tweets (
        tweet_id INTEGER PRIMARY KEY AUTOINCREMENT,
        week_num INTEGER,
        user_handle TEXT NOT NULL,
        display_name TEXT NOT NULL,
        tweet_text TEXT NOT NULL,
        likes TEXT NOT NULL,
        retweets TEXT NOT NULL,
        views TEXT NOT NULL,
        image_path TEXT -- generated photo, relative to static/
    )
    """)

    # Add the photo column to tweet tables created before tweets had photos
    tweet_cols = [col[1] for col in cursor.execute("PRAGMA table_info(historical_tweets)").fetchall()]
    if "image_path" not in tweet_cols:
        cursor.execute("ALTER TABLE historical_tweets ADD COLUMN image_path TEXT")
    
    # Check if schedule table is empty, if so, populate it
    cursor.execute("SELECT COUNT(*) FROM schedule_tracking")
    if cursor.fetchone()[0] == 0:
        full_season_schedule = [
            (1, "Colorado State Rams", 1, 264, 185, 110, 145, "Broderick Donahue (102 Yds, 2 TD)", 31, 17),
            (2, "Boise State Broncos", 0, 0, 0, 0, 0, "TBD", None, None),
            (3, "Air Force Falcons", 0, 0, 0, 0, 0, "TBD", None, None),
            (4, "New Mexico Lobos", 0, 0, 0, 0, 0, "TBD", None, None),
            (5, "Fresno State Bulldogs", 0, 0, 0, 0, 0, "TBD", None, None),
            (6, "San Diego State Aztecs", 0, 0, 0, 0, 0, "TBD", None, None),
            (7, "BYE WEEK", 0, 0, 0, 0, 0, "NONE", None, None),
            (8, "Utah State Aggies", 0, 0, 0, 0, 0, "TBD", None, None),
            (9, "UNLV Rebels", 0, 0, 0, 0, 0, "TBD", None, None),
            (10, "Nevada Wolf Pack", 0, 0, 0, 0, 0, "TBD", None, None),
            (11, "San Jose State Spartans", 0, 0, 0, 0, 0, "TBD", None, None),
            (12, "Washington State Cougars", 0, 0, 0, 0, 0, "TBD", None, None)
        ]
        cursor.executemany("""
        INSERT INTO schedule_tracking (week_id, opponent_name, is_played, wyo_rush_yds, wyo_pass_yds, opp_rush_yds, opp_pass_yds, game_mvp, wyo_score, opp_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, full_season_schedule)
        
    conn.commit()
    conn.close()

def query_full_schedule():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM schedule_tracking ORDER BY week_id ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def query_active_week():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM schedule_tracking WHERE is_played = 0 ORDER BY week_id ASC LIMIT 1")
    row = cursor.fetchone()
    if not row:
        cursor.execute("SELECT * FROM schedule_tracking ORDER BY week_id DESC LIMIT 1")
        row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def query_last_played_week():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM schedule_tracking WHERE is_played = 1 ORDER BY week_id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def query_archived_stories():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM historical_stories ORDER BY week_num DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def query_active_tweets(week_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM historical_tweets WHERE week_num = ? ORDER BY tweet_id DESC", (week_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def save_game_score(week_id, wyo_score, opp_score):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE schedule_tracking SET wyo_score = ?, opp_score = ? WHERE week_id = ?", (wyo_score, opp_score, week_id))
    conn.commit()
    conn.close()

def save_story_to_db(week_id, opponent, text):
    remove_story_image(week_id)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO historical_stories (week_num, opponent_name, generated_text) VALUES (?, ?, ?)", (week_id, opponent, text))
    conn.commit()
    conn.close()

def remove_story_image(week_id):
    """Deletes the hero banner file of a week's story (it's about to be replaced)."""
    conn = get_db_connection()
    row = conn.execute("SELECT image_path FROM historical_stories WHERE week_num = ?", (week_id,)).fetchone()
    conn.close()
    if row and row['image_path'] and os.path.exists(os.path.join(STATIC_DIR, row['image_path'])):
        os.remove(os.path.join(STATIC_DIR, row['image_path']))

def save_story_image(week_id, image_path):
    conn = get_db_connection()
    conn.execute("UPDATE historical_stories SET image_path = ? WHERE week_num = ?", (image_path, week_id))
    conn.commit()
    conn.close()

def query_season_record():
    """(wins, losses) from the played games."""
    games = [g for g in query_full_schedule() if g['is_played'] and g['wyo_score'] is not None]
    wins = sum(1 for g in games if g['wyo_score'] > g['opp_score'])
    return wins, len(games) - wins

def save_tweets_to_db(week_id, tweet_list):
    conn = get_db_connection()
    cursor = conn.cursor()
    # Remove the photo files of the tweets being replaced
    for row in cursor.execute("SELECT image_path FROM historical_tweets WHERE week_num = ? AND image_path IS NOT NULL", (week_id,)).fetchall():
        old_file = os.path.join(STATIC_DIR, row['image_path'])
        if os.path.exists(old_file):
            os.remove(old_file)
    cursor.execute("DELETE FROM historical_tweets WHERE week_num = ?", (week_id,))
    for t in tweet_list:
        cursor.execute("""
            INSERT INTO historical_tweets (week_num, user_handle, display_name, tweet_text, likes, retweets, views, image_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (week_id, t['handle'], t['name'], t['text'], f"{random.randint(10, 95)}K", f"{random.randint(1, 15)}K", f"{random.randint(100, 500)}K", t.get('image_path')))
    conn.commit()
    conn.close()

# Auto-initialize when database.py gets imported by app.py
initialize_database_tables()
