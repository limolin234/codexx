from __future__ import annotations

MEMORY_SCHEMA_VERSION = 1

MEMORY_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_profiles (
  id TEXT PRIMARY KEY,
  scope TEXT NOT NULL,
  summary TEXT NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  confidence REAL NOT NULL,
  max_chars INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_items (
  id TEXT PRIMARY KEY,
  scope TEXT NOT NULL,
  type TEXT NOT NULL,
  title TEXT,
  summary TEXT NOT NULL,
  content TEXT,
  confidence REAL NOT NULL,
  importance REAL NOT NULL,
  status TEXT NOT NULL,
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  expires_at_ms INTEGER,
  source_ref TEXT,
  source_strength TEXT NOT NULL DEFAULT 'unknown',
  stability TEXT NOT NULL DEFAULT 'normal',
  usage_count INTEGER NOT NULL DEFAULT 0,
  last_used_at_ms INTEGER,
  last_evidence_at_ms INTEGER,
  supersedes_id TEXT,
  superseded_by TEXT,
  archived_at_ms INTEGER,
  metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS memory_vectors (
  id TEXT PRIMARY KEY,
  memory_id TEXT NOT NULL,
  label_kind TEXT NOT NULL,
  vector_collection TEXT NOT NULL,
  vector_id TEXT NOT NULL,
  embedding_model TEXT,
  label_text TEXT,
  content_hash TEXT,
  created_at_ms INTEGER NOT NULL,
  FOREIGN KEY(memory_id) REFERENCES memory_items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS memory_facets (
  memory_id TEXT NOT NULL,
  facet_name TEXT NOT NULL,
  facet_text TEXT NOT NULL,
  weight REAL NOT NULL DEFAULT 1.0,
  created_at_ms INTEGER NOT NULL,
  PRIMARY KEY(memory_id, facet_name),
  FOREIGN KEY(memory_id) REFERENCES memory_items(id) ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
  memory_id UNINDEXED,
  scope UNINDEXED,
  type UNINDEXED,
  summary,
  content,
  facets
);

CREATE INDEX IF NOT EXISTS idx_memory_scope_type ON memory_items(scope, type, status);
CREATE INDEX IF NOT EXISTS idx_memory_status_updated ON memory_items(status, updated_at_ms);
CREATE INDEX IF NOT EXISTS idx_memory_superseded_by ON memory_items(superseded_by);
CREATE INDEX IF NOT EXISTS idx_memory_facets_name ON memory_facets(facet_name, memory_id);
"""


def init_memory_schema(conn) -> int:
    conn.executescript(MEMORY_SCHEMA_SQL)
    row = conn.execute("SELECT value FROM schema_meta WHERE key='memory_schema_version'").fetchone()
    current = int(row[0]) if row else 0
    if current > MEMORY_SCHEMA_VERSION:
        raise RuntimeError(f"memory database schema version {current} is newer than runtime {MEMORY_SCHEMA_VERSION}")
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta(key,value) VALUES('memory_schema_version', ?)",
        (str(MEMORY_SCHEMA_VERSION),),
    )
    conn.commit()
    return MEMORY_SCHEMA_VERSION
