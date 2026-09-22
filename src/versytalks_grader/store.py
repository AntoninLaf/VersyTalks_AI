"""SQLite storage: quota counting and idempotency.

One file, no server, no configuration. Correct for a beta at this scale;
swap for Postgres when VersyTalks has its own database to write to.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "grades.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS grades (
    submission_id TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    drill_type    TEXT NOT NULL,
    graded_at     TEXT NOT NULL,
    result_json   TEXT NOT NULL,
    meta_json     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_grades_user ON grades(user_id);
"""


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def find(submission_id):
    """Return a previously stored grade, or None. This is what makes retries safe."""
    with connect() as conn:
        row = conn.execute(
            "SELECT result_json, meta_json FROM grades WHERE submission_id = ?",
            (submission_id,),
        ).fetchone()
    if row is None:
        return None
    return json.loads(row["result_json"]), json.loads(row["meta_json"])


def count_for_user(user_id):
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM grades WHERE user_id = ?", (user_id,)
        ).fetchone()
    return row["n"]


def save(submission_id, user_id, drill_type, result, meta):
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO grades "
            "(submission_id, user_id, drill_type, graded_at, result_json, meta_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                submission_id,
                user_id,
                drill_type,
                datetime.now(timezone.utc).isoformat(),
                json.dumps(result, ensure_ascii=False),
                json.dumps(meta, ensure_ascii=False),
            ),
        )
def count_total():
    with connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM grades").fetchone()
    return row["n"]       