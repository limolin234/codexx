from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from advanced_agent.migrations import MigrationRunner


class SQLiteStore:
    """Small SQLite wrapper used by module-specific stores.

    Agents should depend on higher-level stores/contexts, not this class.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, timeout=30.0, isolation_level=None, check_same_thread=False)
        self._transaction_depth = 0
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute("PRAGMA journal_mode = WAL")
            self.conn.execute("PRAGMA synchronous = NORMAL")
            self.conn.execute("PRAGMA busy_timeout = 30000")
            self.conn.execute("PRAGMA temp_store = MEMORY")

    def init_schema(self) -> None:
        with self._lock:
            MigrationRunner(self.conn).migrate()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, tuple(params))
            if self._transaction_depth == 0:
                self.conn.commit()
            return cur

    def executemany(self, sql: str, params: Iterable[Iterable[Any]]) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.executemany(sql, params)
            if self._transaction_depth == 0:
                self.conn.commit()
            return cur

    @contextlib.contextmanager
    def transaction(self):
        with self._lock:
            outermost = self._transaction_depth == 0
            try:
                self._transaction_depth += 1
                if outermost:
                    self.conn.execute("BEGIN IMMEDIATE")
                yield
            except Exception:
                if outermost:
                    self.conn.rollback()
                raise
            else:
                if outermost:
                    self.conn.commit()
            finally:
                self._transaction_depth -= 1

    @contextlib.contextmanager
    def locked(self):
        """Serialize direct connection access inside one runtime process.

        SQLite WAL and busy_timeout handle multiple MCP server processes using
        separate connections. This lock handles concurrent tool calls inside one
        MCP process when the server invokes handlers from multiple threads.
        """

        with self._lock:
            yield

    def optimize(self) -> None:
        with self._lock:
            self.conn.execute("PRAGMA optimize")
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(sql, tuple(params)).fetchone()

    def query_all(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.conn.execute(sql, tuple(params)).fetchall())


def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def loads(text: str | None) -> Any:
    if not text:
        return None
    return json.loads(text)
