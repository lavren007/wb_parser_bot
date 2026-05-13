import sqlite3
import json
from datetime import datetime
from config import DB_PATH

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                article TEXT,
                filter_type TEXT,
                reviews_count INTEGER,
                questions_count INTEGER,
                avg_rating REAL,
                reviews_file TEXT,
                questions_file TEXT,
                archive_file TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

def save_run(user_id, article, filter_type, reviews_count, questions_count, avg_rating, reviews_file, questions_file, archive_file):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO history (user_id, article, filter_type, reviews_count, questions_count, avg_rating, reviews_file, questions_file, archive_file) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, article, filter_type, reviews_count, questions_count, avg_rating, reviews_file, questions_file, archive_file)
        )
        conn.commit()

def get_history(user_id, limit=10):
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, article, filter_type, reviews_count, questions_count, avg_rating, reviews_file, questions_file, archive_file, created_at FROM history WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
    return rows