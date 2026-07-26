"""Database connection and initialisation."""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "credit.db"


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Open a connection with foreign keys enforced.

    SQLite disables foreign keys on every new connection; without this PRAGMA
    the schema's references are not checked at all.
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialise(path: Path | str = DB_PATH, *, overwrite: bool = False) -> sqlite3.Connection:
    """Create the database from schema.sql and seed_reference_data.sql."""
    path = Path(path)
    if path.exists():
        if not overwrite:
            return connect(path)
        path.unlink()

    conn = connect(path)
    conn.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
    conn.executescript((ROOT / "seed_reference_data.sql").read_text(encoding="utf-8"))
    conn.commit()
    return conn
