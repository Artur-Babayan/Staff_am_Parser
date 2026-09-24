import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "staff_am_bot.db")

MAX_FILTER_LENGTH = 50
MAX_FILTERS_PER_USER = 20


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def init_db():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                created_at TEXT NOT NULL,
                username TEXT,
                first_name TEXT,
                language_code TEXT
            )
            """
        )
        for column in ("username", "first_name", "language_code"):
            if not _column_exists(conn, "users", column):
                conn.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS filters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                initialized INTEGER NOT NULL DEFAULT 1,
                UNIQUE(chat_id, keyword),
                FOREIGN KEY(chat_id) REFERENCES users(chat_id)
            )
            """
        )
        if not _column_exists(conn, "filters", "initialized"):
            conn.execute(
                "ALTER TABLE filters ADD COLUMN initialized INTEGER NOT NULL DEFAULT 1"
            )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_jobs (
                chat_id INTEGER NOT NULL,
                job_id INTEGER NOT NULL,
                seen_at TEXT NOT NULL,
                PRIMARY KEY (chat_id, job_id),
                FOREIGN KEY(chat_id) REFERENCES users(chat_id)
            )
            """
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_user(chat_id: int, username: str = None, first_name: str = None, language_code: str = None) -> bool:
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM users WHERE chat_id = ?", (chat_id,)
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE users
                SET username = ?, first_name = ?, language_code = ?
                WHERE chat_id = ?
                """,
                (username, first_name, language_code, chat_id),
            )
            return False

        conn.execute(
            """
            INSERT INTO users (chat_id, created_at, username, first_name, language_code)
            VALUES (?, ?, ?, ?, ?)
            """,
            (chat_id, _now(), username, first_name, language_code),
        )
        return True


def get_all_user_ids() -> list:
    with get_connection() as conn:
        rows = conn.execute("SELECT chat_id FROM users").fetchall()
        return [row["chat_id"] for row in rows]


def get_user_info(chat_id: int) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT chat_id, username, first_name, language_code, created_at FROM users WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        return dict(row) if row else None


def load_filters(chat_id: int) -> list:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT keyword FROM filters WHERE chat_id = ? ORDER BY id", (chat_id,)
        ).fetchall()
        return [row["keyword"] for row in rows]


def load_filter_records(chat_id: int) -> list:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, keyword, initialized FROM filters WHERE chat_id = ? ORDER BY id",
            (chat_id,)
        ).fetchall()
        return [dict(row) for row in rows]


def add_filter(chat_id: int, keyword: str) -> tuple[str, list]:
    keyword = keyword.strip()
    if not keyword:
        return "empty", load_filters(chat_id)
    if len(keyword) > MAX_FILTER_LENGTH:
        return "too_long", load_filters(chat_id)

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT 1 FROM filters WHERE chat_id = ? AND LOWER(keyword) = LOWER(?)",
            (chat_id, keyword),
        ).fetchone()
        if existing:
            return "duplicate", load_filters(chat_id)

        count = conn.execute(
            "SELECT COUNT(*) FROM filters WHERE chat_id = ?", (chat_id,)
        ).fetchone()[0]
        if count >= MAX_FILTERS_PER_USER:
            return "limit", load_filters(chat_id)

        conn.execute(
            "INSERT INTO filters (chat_id, keyword, initialized) VALUES (?, ?, 0)",
            (chat_id, keyword),
        )

    return "added", load_filters(chat_id)


def remove_filter(chat_id: int, keyword: str) -> tuple[bool, list]:
    keyword = keyword.strip()
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM filters WHERE chat_id = ? AND LOWER(keyword) = LOWER(?)",
            (chat_id, keyword),
        )
        removed = cursor.rowcount > 0
    return removed, load_filters(chat_id)


def remove_filter_by_id(chat_id: int, filter_id: int) -> tuple[bool, str | None, list]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT keyword FROM filters WHERE id = ? AND chat_id = ?",
            (filter_id, chat_id),
        ).fetchone()
        if row is None:
            return False, None, load_filters(chat_id)

        conn.execute(
            "DELETE FROM filters WHERE id = ? AND chat_id = ?",
            (filter_id, chat_id),
        )
        keyword = row["keyword"]

    return True, keyword, load_filters(chat_id)


def initialize_filter(chat_id: int, filter_id: int, job_ids: list) -> bool:
    valid_job_ids = [job_id for job_id in job_ids if job_id is not None]
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE filters SET initialized = 1 WHERE id = ? AND chat_id = ? AND initialized = 0",
            (filter_id, chat_id),
        )
        if cursor.rowcount == 0:
            return False

        seen_at = _now()
        conn.executemany(
            "INSERT OR IGNORE INTO seen_jobs (chat_id, job_id, seen_at) VALUES (?, ?, ?)",
            [(chat_id, job_id, seen_at) for job_id in valid_job_ids],
        )
    return True


def is_job_seen(chat_id: int, job_id: int) -> bool:
    if job_id is None:
        return True

    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM seen_jobs WHERE chat_id = ? AND job_id = ?",
            (chat_id, job_id),
        ).fetchone()
        return row is not None


def mark_job_seen(chat_id: int, job_id: int):
    if job_id is None:
        return

    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_jobs (chat_id, job_id, seen_at) VALUES (?, ?, ?)",
            (chat_id, job_id, _now()),
        )


def cleanup_old_seen_jobs(days: int = 30):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM seen_jobs WHERE seen_at < datetime('now', ?)",
            (f"-{days} days",),
        )


init_db()