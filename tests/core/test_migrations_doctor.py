from advanced_agent.doctor import Doctor
from advanced_agent.migrations import CURRENT_SCHEMA_VERSION, MigrationRunner
from advanced_agent.stores.sqlite_store import SQLiteStore


def test_migration_runner_sets_version(tmp_path) -> None:
    db = SQLiteStore(tmp_path / "state.sqlite")
    db.init_schema()
    assert MigrationRunner(db.conn).version() == CURRENT_SCHEMA_VERSION


def test_doctor_reports_core_checks(tmp_path) -> None:
    report = Doctor(tmp_path / "doctor.sqlite", config_path=tmp_path / "missing.json", plugin_dir="plugins").run()
    assert report.checks["sqlite"]
    assert report.checks["schema_version"]
    assert report.checks["sqlite_vec"]
    assert "codex_cli" in report.checks
