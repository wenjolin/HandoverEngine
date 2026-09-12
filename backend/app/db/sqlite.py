import sqlite3
from pathlib import Path

_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    input_zip_path TEXT,
    work_dir TEXT NOT NULL,
    output_zip_path TEXT,
    output_pdf_path TEXT,
    options TEXT NOT NULL,
    progress TEXT NOT NULL,
    error TEXT,
    stats TEXT
)
"""


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(_JOBS_TABLE)
        conn.commit()
