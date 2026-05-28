import sqlite3

from advanced_agent.migrations import CURRENT_SCHEMA_VERSION, MigrationRunner


def test_migration_v1_to_v2_adds_label_text(tmp_path) -> None:
    db = tmp_path / "old.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO schema_meta(key,value) VALUES('schema_version','1')")
    conn.execute(
        """CREATE TABLE memory_vectors (
        id TEXT PRIMARY KEY,
        memory_id TEXT NOT NULL,
        label_kind TEXT NOT NULL,
        vector_collection TEXT NOT NULL,
        vector_id TEXT NOT NULL,
        embedding_model TEXT,
        content_hash TEXT,
        created_at_ms INTEGER NOT NULL
        )"""
    )
    conn.commit()

    status = MigrationRunner(conn).migrate()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(memory_vectors)")}
    assert status.current_version == CURRENT_SCHEMA_VERSION
    assert "label_text" in columns
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='memory_facets'").fetchone()
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='memory_fts'").fetchone()


def test_migration_v2_to_v3_backfills_facets_and_fts(tmp_path) -> None:
    db = tmp_path / "v2.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO schema_meta(key,value) VALUES('schema_version','2')")
    conn.execute(
        """CREATE TABLE memory_items (
        id TEXT PRIMARY KEY, scope TEXT NOT NULL, type TEXT NOT NULL, title TEXT,
        summary TEXT NOT NULL, content TEXT, confidence REAL NOT NULL, importance REAL NOT NULL,
        status TEXT NOT NULL, created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL,
        expires_at_ms INTEGER, source_ref TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE memory_vectors (
        id TEXT PRIMARY KEY, memory_id TEXT NOT NULL, label_kind TEXT NOT NULL,
        vector_collection TEXT NOT NULL, vector_id TEXT NOT NULL, embedding_model TEXT,
        label_text TEXT, content_hash TEXT, created_at_ms INTEGER NOT NULL
        )"""
    )
    conn.execute(
        "INSERT INTO memory_items(id,scope,type,summary,content,confidence,importance,status,created_at_ms,updated_at_ms) VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("mem1", "project:test", "decision", "hybrid search decision", "FTS and facet table", 0.8, 0.7, "active", 1, 1),
    )
    conn.execute(
        "INSERT INTO memory_vectors(id,memory_id,label_kind,vector_collection,vector_id,label_text,created_at_ms) VALUES(?,?,?,?,?,?,?)",
        ("vec1", "mem1", "decision", "vec_memory", "1", "decision facet text", 1),
    )
    conn.commit()

    status = MigrationRunner(conn).migrate()
    assert status.current_version == CURRENT_SCHEMA_VERSION
    facet = conn.execute("SELECT facet_name, facet_text FROM memory_facets WHERE memory_id='mem1' AND facet_name='decision'").fetchone()
    assert facet == ("decision", "decision facet text")
    fts = conn.execute("SELECT memory_id FROM memory_fts WHERE memory_fts MATCH 'hybrid'").fetchone()
    assert fts[0] == "mem1"


def test_migration_v3_to_v4_moves_project_facet_to_workstream(tmp_path) -> None:
    db = tmp_path / "v3.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO schema_meta(key,value) VALUES('schema_version','3')")
    conn.execute(
        """CREATE TABLE memory_items (
        id TEXT PRIMARY KEY, scope TEXT NOT NULL, type TEXT NOT NULL, title TEXT,
        summary TEXT NOT NULL, content TEXT, confidence REAL NOT NULL, importance REAL NOT NULL,
        status TEXT NOT NULL, created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL,
        expires_at_ms INTEGER, source_ref TEXT
        )"""
    )
    conn.execute(
        """CREATE TABLE memory_vectors (
        id TEXT PRIMARY KEY, memory_id TEXT NOT NULL, label_kind TEXT NOT NULL,
        vector_collection TEXT NOT NULL, vector_id TEXT NOT NULL, embedding_model TEXT,
        label_text TEXT, content_hash TEXT, created_at_ms INTEGER NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE memory_facets (
        memory_id TEXT NOT NULL, facet_name TEXT NOT NULL, facet_text TEXT NOT NULL,
        weight REAL NOT NULL DEFAULT 1.0, created_at_ms INTEGER NOT NULL,
        PRIMARY KEY(memory_id, facet_name)
        )"""
    )
    conn.execute("CREATE VIRTUAL TABLE memory_fts USING fts5(memory_id UNINDEXED, scope UNINDEXED, type UNINDEXED, summary, content, facets)")
    conn.execute(
        "INSERT INTO memory_items(id,scope,type,summary,content,confidence,importance,status,created_at_ms,updated_at_ms) VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("mem1", "topic:test", "decision", "legacy project facet", "content", 0.8, 0.7, "active", 1, 1),
    )
    conn.execute("INSERT INTO memory_facets(memory_id,facet_name,facet_text,weight,created_at_ms) VALUES(?,?,?,?,?)", ("mem1", "project", "legacy project text", 1.0, 1))
    conn.execute("INSERT INTO memory_vectors(id,memory_id,label_kind,vector_collection,vector_id,label_text,created_at_ms) VALUES(?,?,?,?,?,?,?)", ("vec1", "mem1", "project", "vec_memory", "1", "legacy project text", 1))
    conn.commit()

    status = MigrationRunner(conn).migrate()
    assert status.current_version == CURRENT_SCHEMA_VERSION
    assert conn.execute("SELECT 1 FROM memory_facets WHERE facet_name='project'").fetchone() is None
    assert conn.execute("SELECT facet_text FROM memory_facets WHERE facet_name='workstream'").fetchone()[0] == "legacy project text"
    assert conn.execute("SELECT label_kind FROM memory_vectors WHERE id='vec1'").fetchone()[0] == "workstream"
