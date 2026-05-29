from __future__ import annotations

from dataclasses import dataclass

from advanced_agent.stores.schema import SCHEMA_SQL

CURRENT_SCHEMA_VERSION = 5


@dataclass(slots=True)
class MigrationStatus:
    current_version: int
    target_version: int
    upgraded: bool


class MigrationRunner:
    """Idempotent SQLite schema/version manager.

    Version 1 is the current bootstrap schema. Future versions should add
    ordered migrations instead of editing existing deployed schema in place.
    """

    def __init__(self, conn) -> None:
        self.conn = conn

    def migrate(self) -> MigrationStatus:
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        row = self.conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
        current = int(row[0]) if row else 0
        upgraded = False
        if current == 0:
            self.conn.executescript(SCHEMA_SQL)
            self._set_version(CURRENT_SCHEMA_VERSION)
            upgraded = True
            current = CURRENT_SCHEMA_VERSION
        elif current < CURRENT_SCHEMA_VERSION:
            if current < 2:
                self._migrate_to_v2()
            if current < 3:
                self._migrate_to_v3()
            if current < 4:
                self._migrate_to_v4()
            if current < 5:
                self._migrate_to_v5()
            self._set_version(CURRENT_SCHEMA_VERSION)
            upgraded = True
            current = CURRENT_SCHEMA_VERSION
        elif current > CURRENT_SCHEMA_VERSION:
            raise RuntimeError(f"database schema version {current} is newer than runtime {CURRENT_SCHEMA_VERSION}")
        self.conn.commit()
        return MigrationStatus(current_version=current, target_version=CURRENT_SCHEMA_VERSION, upgraded=upgraded)

    def version(self) -> int:
        self.conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        row = self.conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
        return int(row[0]) if row else 0

    def _set_version(self, version: int) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version', ?)",
            (str(version),),
        )

    def _migrate_to_v2(self) -> None:
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(memory_vectors)").fetchall()}
        if "label_text" not in columns:
            self.conn.execute("ALTER TABLE memory_vectors ADD COLUMN label_text TEXT")

    def _migrate_to_v3(self) -> None:
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS memory_facets (
            memory_id TEXT NOT NULL,
            facet_name TEXT NOT NULL,
            facet_text TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 1.0,
            created_at_ms INTEGER NOT NULL,
            PRIMARY KEY(memory_id, facet_name),
            FOREIGN KEY(memory_id) REFERENCES memory_items(id) ON DELETE CASCADE
            )"""
        )
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_facets_name ON memory_facets(facet_name, memory_id)")
        self.conn.execute(
            """CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
            memory_id UNINDEXED,
            scope UNINDEXED,
            type UNINDEXED,
            summary,
            content,
            facets
            )"""
        )
        self._backfill_memory_facets()
        self._backfill_memory_fts()

    def _backfill_memory_facets(self) -> None:
        if not self._table_exists("memory_vectors"):
            return
        rows = self.conn.execute(
            """SELECT memory_id, label_kind, label_text, MIN(created_at_ms) AS created_at_ms
            FROM memory_vectors
            WHERE label_text IS NOT NULL AND LENGTH(label_text)>0
            GROUP BY memory_id, label_kind"""
        ).fetchall()
        for row in rows:
            self.conn.execute(
                """INSERT OR IGNORE INTO memory_facets(memory_id, facet_name, facet_text, weight, created_at_ms)
                VALUES(?,?,?,?,?)""",
                (row[0], row[1], row[2], 1.0, row[3]),
            )

    def _backfill_memory_fts(self) -> None:
        if not self._table_exists("memory_items"):
            return
        rows = self.conn.execute(
            """SELECT mi.id, mi.scope, mi.type, mi.summary, mi.content,
            COALESCE(group_concat(mf.facet_name || ': ' || mf.facet_text, '\n'), '') AS facets
            FROM memory_items mi
            LEFT JOIN memory_facets mf ON mf.memory_id=mi.id
            WHERE mi.status='active'
            GROUP BY mi.id"""
        ).fetchall()
        for row in rows:
            self.conn.execute(
                """INSERT INTO memory_fts(memory_id, scope, type, summary, content, facets)
                VALUES(?,?,?,?,?,?)""",
                (row[0], row[1], row[2], row[3], row[4] or "", row[5] or ""),
            )

    def _migrate_to_v4(self) -> None:
        """Remove legacy `project` facet by migrating it into `workstream`.

        v4 intentionally stops carrying project as a separate memory dimension:
        workstream is the topic/project dimension, workspace is the filesystem
        dimension. Existing project facet rows/vectors are converted instead of
        left as compatibility debris.
        """

        if self._table_exists("memory_facets"):
            rows = self.conn.execute(
                "SELECT memory_id, facet_text, weight, created_at_ms FROM memory_facets WHERE facet_name='project'"
            ).fetchall()
            for row in rows:
                existing = self.conn.execute(
                    "SELECT facet_text FROM memory_facets WHERE memory_id=? AND facet_name='workstream'",
                    (row[0],),
                ).fetchone()
                if existing:
                    merged = self._merge_text(existing[0], row[1])
                    self.conn.execute(
                        "UPDATE memory_facets SET facet_text=?, weight=MAX(weight, ?) WHERE memory_id=? AND facet_name='workstream'",
                        (merged, row[2], row[0]),
                    )
                else:
                    self.conn.execute(
                        """INSERT INTO memory_facets(memory_id, facet_name, facet_text, weight, created_at_ms)
                        VALUES(?,?,?,?,?)""",
                        (row[0], "workstream", row[1], row[2], row[3]),
                    )
            self.conn.execute("DELETE FROM memory_facets WHERE facet_name='project'")
        if self._table_exists("memory_vectors"):
            rows = self.conn.execute(
                "SELECT id, memory_id, label_text FROM memory_vectors WHERE label_kind='project'"
            ).fetchall()
            for row in rows:
                existing = self.conn.execute(
                    "SELECT id, label_text FROM memory_vectors WHERE memory_id=? AND label_kind='workstream' LIMIT 1",
                    (row[1],),
                ).fetchone()
                if existing:
                    merged = self._merge_text(existing[1], row[2])
                    self.conn.execute("UPDATE memory_vectors SET label_text=? WHERE id=?", (merged, existing[0]))
                    self.conn.execute("DELETE FROM memory_vectors WHERE id=?", (row[0],))
                else:
                    self.conn.execute("UPDATE memory_vectors SET label_kind='workstream' WHERE id=?", (row[0],))
        if self._table_exists("memory_fts"):
            self.conn.execute("DELETE FROM memory_fts")
            self._backfill_memory_fts()

    def _migrate_to_v5(self) -> None:
        """Add memory lifecycle metadata for profile maintenance and cleanup."""

        if not self._table_exists("memory_items"):
            return
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(memory_items)").fetchall()}
        additions = {
            "source_strength": "TEXT NOT NULL DEFAULT 'unknown'",
            "stability": "TEXT NOT NULL DEFAULT 'normal'",
            "usage_count": "INTEGER NOT NULL DEFAULT 0",
            "last_used_at_ms": "INTEGER",
            "last_evidence_at_ms": "INTEGER",
            "supersedes_id": "TEXT",
            "superseded_by": "TEXT",
            "archived_at_ms": "INTEGER",
            "metadata_json": "TEXT",
        }
        for name, definition in additions.items():
            if name not in columns:
                self.conn.execute(f"ALTER TABLE memory_items ADD COLUMN {name} {definition}")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_status_updated ON memory_items(status, updated_at_ms)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_memory_superseded_by ON memory_items(superseded_by)")

    def _merge_text(self, left: str | None, right: str | None) -> str:
        parts = []
        seen = set()
        for item in (left, right):
            text = (item or "").strip()
            if text and text not in seen:
                seen.add(text)
                parts.append(text)
        return "\n".join(parts)

    def _table_exists(self, name: str) -> bool:
        row = self.conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','virtual table') AND name=?", (name,)).fetchone()
        return row is not None
