import sqlite3

from advanced_agent.migrations import CURRENT_SCHEMA_VERSION, MigrationRunner


def test_migration_v7_to_v8_drops_runtime_memory_tables(tmp_path) -> None:
    db = tmp_path / "v7.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO schema_meta(key,value) VALUES('schema_version','7')")
    conn.execute("CREATE TABLE memory_items (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE memory_vectors (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE memory_facets (memory_id TEXT, facet_name TEXT)")
    conn.execute("CREATE VIRTUAL TABLE memory_fts USING fts5(memory_id UNINDEXED, summary)")
    conn.execute("CREATE TABLE user_profiles (id TEXT PRIMARY KEY)")
    conn.commit()

    status = MigrationRunner(conn).migrate()
    assert status.current_version == CURRENT_SCHEMA_VERSION
    for table in ("memory_items", "memory_vectors", "memory_facets", "memory_fts", "user_profiles"):
        assert conn.execute("SELECT name FROM sqlite_master WHERE name=?", (table,)).fetchone() is None

def test_migration_v5_to_v6_adds_injection_ledger(tmp_path) -> None:
    db = tmp_path / "v5.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO schema_meta(key,value) VALUES('schema_version','5')")
    conn.commit()

    status = MigrationRunner(conn).migrate()
    assert status.current_version == CURRENT_SCHEMA_VERSION
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='session_injection_ledger'").fetchone()
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(session_injection_ledger)")}
    assert "idx_injection_ledger_session" in indexes
