#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

from advanced_agent import defaults
from advanced_agent.memory_facets import normalize_facets
from advanced_agent.runtime.app import RuntimeApp


def rebuild(db_path: Path, config_path: Path | None = None, backup: bool = True, dry_run: bool = False) -> int:
    db_path = db_path.resolve()
    if backup and db_path.exists() and not dry_run:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = db_path.with_suffix(db_path.suffix + f".pre-keywords-{stamp}.bak")
        shutil.copy2(db_path, backup_path)
        print(f"backup: {backup_path}")
    app = RuntimeApp.create(db_path, config_path=config_path)
    rows = app.db.query_all(
        "SELECT id, scope, type, summary, content, created_at_ms, updated_at_ms FROM memory_items WHERE status='active' ORDER BY created_at_ms"
    )
    changed = 0
    for row in rows:
        text = f"{row['summary']}\n{row['content'] or ''}".strip()
        aligned = app.memory.indexer.alignment.labels_for(text, agent_role="migration")
        labels = normalize_facets(
            aligned,
            summary=row["summary"],
            content=row["content"] or row["summary"],
            type_=row["type"],
            metadata={"scope": row["scope"], "created_at_ms": row["created_at_ms"], "updated_at_ms": row["updated_at_ms"]},
        )
        if dry_run:
            print(f"{row['id']} {row['type']} labels={','.join(labels)} summary={row['summary'][:80]}")
        else:
            app.vectors.replace_memory_labels(row["id"], labels)
        changed += 1
    print(f"migrated memories: {changed} dry_run={dry_run}")
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild memory vectors/facets with the compact semantic+keywords label strategy.")
    parser.add_argument("--db", default=defaults.default_db())
    parser.add_argument("--config", default=defaults.default_config())
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    rebuild(Path(args.db), Path(args.config) if args.config else None, backup=not args.no_backup, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
