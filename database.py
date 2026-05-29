"""Persystencja stanu monitorowanych pozycji (SQLite)."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)


@dataclass
class StoredSnapshot:
    """Ostatni zapisany stan dla danego URL."""

    url: str
    last_price: float | None
    last_availability: str | None
    last_notified_price: float | None


class StateDatabase:
    """Prosta baza SQLite zapamiętująca poprzednie ceny (anty-spam)."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    url TEXT PRIMARY KEY,
                    last_price REAL,
                    last_availability TEXT,
                    last_notified_price REAL,
                    updated_at TEXT DEFAULT (datetime('now'))
                )
                """
            )

    def get_snapshot(self, url: str) -> StoredSnapshot | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT url, last_price, last_availability, last_notified_price "
                "FROM snapshots WHERE url = ?",
                (url,),
            ).fetchone()

        if row is None:
            return None

        return StoredSnapshot(
            url=row["url"],
            last_price=row["last_price"],
            last_availability=row["last_availability"],
            last_notified_price=row["last_notified_price"],
        )

    def save_snapshot(
        self,
        url: str,
        *,
        last_price: float | None,
        last_availability: str | None,
        last_notified_price: float | None,
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO snapshots (
                    url, last_price, last_availability, last_notified_price, updated_at
                ) VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(url) DO UPDATE SET
                    last_price = excluded.last_price,
                    last_availability = excluded.last_availability,
                    last_notified_price = excluded.last_notified_price,
                    updated_at = datetime('now')
                """,
                (url, last_price, last_availability, last_notified_price),
            )
        logger.debug("Zapisano stan dla %s", url)
