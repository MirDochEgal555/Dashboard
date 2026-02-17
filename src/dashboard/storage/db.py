from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

CACHE_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache_entries (
    key TEXT PRIMARY KEY,
    json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    ttl_seconds INTEGER NOT NULL CHECK (ttl_seconds >= 0)
);
"""


def _prepare_db_path(db_path: Path) -> Path:
    normalized = Path(db_path)
    normalized.parent.mkdir(parents=True, exist_ok=True)
    return normalized


def connect(db_path: Path) -> sqlite3.Connection:
    normalized = _prepare_db_path(db_path)
    connection = sqlite3.connect(normalized)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL;")
    connection.execute("PRAGMA synchronous = NORMAL;")
    return connection


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(CACHE_TABLE_SCHEMA)
    connection.commit()


@contextmanager
def open_db(db_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(db_path)
    try:
        ensure_schema(connection)
        yield connection
    finally:
        connection.close()


def initialize_database(db_path: Path) -> None:
    with open_db(db_path):
        return
