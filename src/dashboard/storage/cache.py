from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import open_db


@dataclass(slots=True)
class CacheEntry:
    key: str
    payload: Any
    fetched_at: datetime
    ttl_seconds: int

    def is_stale(self, now: datetime | None = None) -> bool:
        reference = now or datetime.now(timezone.utc)
        return (reference - self.fetched_at).total_seconds() > self.ttl_seconds


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return _normalize_datetime(parsed)


def set_cache_entry(
    db_path: Path,
    key: str,
    payload: Any,
    ttl_seconds: int,
    *,
    fetched_at: datetime | None = None,
) -> None:
    if ttl_seconds < 0:
        raise ValueError("ttl_seconds must be >= 0")

    record_time = _normalize_datetime(fetched_at) if fetched_at is not None else _utc_now()
    payload_json = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))

    with open_db(db_path) as connection:
        connection.execute(
            """
            INSERT INTO cache_entries (key, json, fetched_at, ttl_seconds)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                json=excluded.json,
                fetched_at=excluded.fetched_at,
                ttl_seconds=excluded.ttl_seconds
            """,
            (key, payload_json, record_time.isoformat(), ttl_seconds),
        )
        connection.commit()


def get_cache_entry(db_path: Path, key: str) -> CacheEntry | None:
    with open_db(db_path) as connection:
        row = connection.execute(
            "SELECT key, json, fetched_at, ttl_seconds FROM cache_entries WHERE key = ?",
            (key,),
        ).fetchone()

    if row is None:
        return None

    return CacheEntry(
        key=row["key"],
        payload=json.loads(row["json"]),
        fetched_at=_parse_datetime(row["fetched_at"]),
        ttl_seconds=int(row["ttl_seconds"]),
    )


def get_cache_payload(db_path: Path, key: str, *, allow_stale: bool = False) -> Any | None:
    entry = get_cache_entry(db_path, key)
    if entry is None:
        return None
    if not allow_stale and entry.is_stale():
        return None
    return entry.payload


def list_cache_keys(db_path: Path) -> list[str]:
    with open_db(db_path) as connection:
        rows = connection.execute("SELECT key FROM cache_entries ORDER BY key ASC").fetchall()
    return [str(row["key"]) for row in rows]


def prune_expired_entries(db_path: Path, *, now: datetime | None = None) -> int:
    reference = _normalize_datetime(now) if now is not None else _utc_now()
    deleted = 0

    with open_db(db_path) as connection:
        rows = connection.execute("SELECT key, fetched_at, ttl_seconds FROM cache_entries").fetchall()
        for row in rows:
            fetched_at = _parse_datetime(row["fetched_at"])
            ttl_seconds = int(row["ttl_seconds"])
            if (reference - fetched_at).total_seconds() > ttl_seconds:
                connection.execute("DELETE FROM cache_entries WHERE key = ?", (row["key"],))
                deleted += 1
        connection.commit()

    return deleted
