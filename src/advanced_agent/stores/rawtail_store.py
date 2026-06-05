from __future__ import annotations

from advanced_agent.models import new_id
from advanced_agent.stores.sqlite_store import SQLiteStore

RAWTAIL_SCHEMA_VERSION = 1

RAWTAIL_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rawtail_chunks (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  source TEXT NOT NULL,
  role TEXT NOT NULL,
  text TEXT NOT NULL,
  request_id TEXT,
  seq INTEGER,
  created_at_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rawtail_session_time ON rawtail_chunks(session_id, created_at_ms DESC, seq DESC);
CREATE INDEX IF NOT EXISTS idx_rawtail_time ON rawtail_chunks(created_at_ms);
"""


def init_rawtail_schema(db: SQLiteStore) -> None:
    with db.locked():
        db.conn.executescript(RAWTAIL_SCHEMA_SQL)
        row = db.conn.execute("SELECT value FROM schema_meta WHERE key='rawtail_schema_version'").fetchone()
        current = int(row[0]) if row else 0
        if current > RAWTAIL_SCHEMA_VERSION:
            raise RuntimeError(f"rawtail database schema version {current} is newer than runtime {RAWTAIL_SCHEMA_VERSION}")
        db.conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key,value) VALUES('rawtail_schema_version', ?)",
            (str(RAWTAIL_SCHEMA_VERSION),),
        )
        db.conn.commit()


class RawTailStore:
    """Bounded cleaned raw-tail cache stored separately from durable memory."""

    def __init__(self, db: SQLiteStore, max_bytes: int = 10 * 1024 * 1024) -> None:
        self.db = db
        self.max_bytes = max(0, int(max_bytes))

    def has_request(self, session_id: str, request_id: str, role: str | None = None) -> bool:
        if role is None:
            row = self.db.query_one("SELECT 1 FROM rawtail_chunks WHERE session_id=? AND request_id=? LIMIT 1", (session_id, request_id))
        else:
            row = self.db.query_one("SELECT 1 FROM rawtail_chunks WHERE session_id=? AND request_id=? AND role=? LIMIT 1", (session_id, request_id, role))
        return row is not None

    def append_chunk(
        self,
        *,
        session_id: str,
        source: str,
        role: str,
        text: str,
        created_at_ms: int,
        request_id: str | None = None,
        seq: int | None = None,
        chunk_id: str | None = None,
    ) -> str | None:
        clean = text.strip()
        if not clean:
            return None
        cid = chunk_id or new_id("rawtail")
        self.db.execute(
            """INSERT OR IGNORE INTO rawtail_chunks
            (id,session_id,source,role,text,request_id,seq,created_at_ms)
            VALUES(?,?,?,?,?,?,?,?)""",
            (cid, session_id, source, role, clean, request_id, seq, created_at_ms),
        )
        self.prune_to_limit()
        return cid

    def lines(self, session_id: str, limit: int = 80, max_chars: int = 800) -> list[str]:
        rows = list(reversed(self.db.query_all(
            """SELECT created_at_ms, source, role, text, request_id, seq
            FROM rawtail_chunks WHERE session_id=?
            ORDER BY created_at_ms DESC, seq DESC, rowid DESC LIMIT ?""",
            (session_id, max(1, int(limit))),
        )))
        max_chars = max(1, int(max_chars))
        return [
            f"{row['created_at_ms']} {row['source']}/{row['role']} req={row['request_id'] or '-'}: {str(row['text'])[:max_chars]}"
            for row in rows
        ]

    def prune_to_limit(self) -> int:
        if self.max_bytes <= 0:
            return 0
        try:
            size = self.db.path.stat().st_size
        except OSError:
            return 0
        if size <= self.max_bytes:
            return 0
        deleted = 0
        # Delete in small batches. WAL may keep disk size high until checkpoint,
        # but live rows stay bounded and restart remains safe after hard kills.
        while size > self.max_bytes:
            rows = self.db.query_all("SELECT id FROM rawtail_chunks ORDER BY created_at_ms, seq, rowid LIMIT 200", ())
            if not rows:
                break
            ids = [row["id"] for row in rows]
            placeholders = ",".join("?" for _ in ids)
            deleted += self.db.execute(f"DELETE FROM rawtail_chunks WHERE id IN ({placeholders})", ids).rowcount
            try:
                self.db.conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
                self.db.conn.commit()
                size = self.db.path.stat().st_size
            except OSError:
                break
        return deleted
