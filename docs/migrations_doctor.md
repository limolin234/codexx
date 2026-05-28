# Migrations and Doctor

Long-lived local software needs explicit schema/version checks. The runtime should not rely only on `CREATE TABLE IF NOT EXISTS` forever.

## MigrationRunner

`MigrationRunner` owns schema versioning.

Current version:

```text
CURRENT_SCHEMA_VERSION = 1
```

Version 1 is the bootstrap schema. Future schema changes should add ordered migrations rather than silently relying on ad-hoc table creation.

## Doctor

Run:

```bash
PYTHONPATH=src .venv/bin/python -m advanced_agent.doctor --db runtime/doctor.sqlite --config .env.json
```

Checks:

- SQLite open/health;
- schema version;
- sqlite-vec load;
- Codex CLI presence;
- JSON model config load;
- role model/key configuration;
- plugin manifest validation.

Network model calls are not performed by default.
