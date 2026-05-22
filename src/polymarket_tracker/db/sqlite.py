from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from polymarket_tracker.config.settings import sqlite_path
from polymarket_tracker.utils.time import iso_now


class Database:
    def __init__(self, database_url: str, busy_timeout_ms: int = 5000) -> None:
        self.path = sqlite_path(database_url)
        self.busy_timeout_ms = busy_timeout_ms
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        self.connection.execute("PRAGMA journal_mode = WAL")

    def close(self) -> None:
        self.connection.close()

    def migrate(self, migrations_dir: str | Path = "migrations") -> None:
        directory = Path(migrations_dir)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        for path in sorted(directory.glob("*.sql")):
            version = path.stem
            if self.fetchone("SELECT version FROM schema_migrations WHERE version = ?", (version,)):
                continue
            self.connection.executescript(path.read_text(encoding="utf-8"))
            self.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, iso_now()),
            )
            self.connection.commit()

    def execute(self, sql: str, params: Iterable[Any] | Mapping[str, Any] = ()) -> sqlite3.Cursor:
        if isinstance(params, Mapping):
            return self.connection.execute(sql, params)
        return self.connection.execute(sql, tuple(params))

    def executemany(self, sql: str, params: Iterable[Iterable[Any]]) -> sqlite3.Cursor:
        return self.connection.executemany(sql, params)

    def fetchone(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        return self.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return list(self.execute(sql, params).fetchall())

    def transaction(self) -> _Transaction:
        return _Transaction(self.connection)

    def health(self) -> str:
        try:
            self.connection.execute("SELECT 1").fetchone()
            return "OK"
        except sqlite3.Error as exc:
            return f"ERROR: {exc}"


class _Transaction:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def __enter__(self) -> sqlite3.Connection:
        self.connection.execute("BEGIN")
        return self.connection

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type:
            self.connection.rollback()
        else:
            self.connection.commit()
