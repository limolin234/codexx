from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from advanced_agent.config import RuntimeConfig
from advanced_agent.migrations import CURRENT_SCHEMA_VERSION, MigrationRunner
from advanced_agent.plugins import PluginRegistry, PluginValidationError
from advanced_agent.runtime.app import RuntimeApp


@dataclass(slots=True)
class DoctorReport:
    ok: bool
    checks: dict[str, bool]
    details: dict[str, str]


class Doctor:
    def __init__(self, db_path: str | Path, config_path: str | Path | None = None, plugin_dir: str | Path = "plugins") -> None:
        self.db_path = db_path
        self.config_path = config_path
        self.plugin_dir = plugin_dir

    def run(self, check_models: bool = False) -> DoctorReport:
        checks: dict[str, bool] = {}
        details: dict[str, str] = {}

        try:
            app = RuntimeApp.create(self.db_path, config_path=self.config_path)
            checks["sqlite"] = app.health.check().ok
            details["sqlite"] = "ok"
            version = MigrationRunner(app.db.conn).version()
            checks["schema_version"] = version == CURRENT_SCHEMA_VERSION
            details["schema_version"] = f"{version}/{CURRENT_SCHEMA_VERSION}"
            checks["sqlite_vec"] = bool(app.db.query_one("SELECT vec_version() AS v"))
            details["sqlite_vec"] = "ok"
        except Exception as exc:
            checks["sqlite"] = False
            details["sqlite"] = repr(exc)

        codex = shutil.which("codex")
        checks["codex_cli"] = codex is not None
        details["codex_cli"] = codex or "not found"

        cfg = RuntimeConfig.load(self.config_path)
        checks["config_load"] = True
        details["config_load"] = "ok" if self.config_path is None or Path(self.config_path).exists() else "missing; using defaults"
        for role in ("interactive_model", "main_model", "audit_model"):
            model = cfg.model_for_role(role)
            if model is None:
                checks[f"{role}_configured"] = False
                details[f"{role}_configured"] = "not configured/default"
            else:
                has_key = bool(model.resolved_api_key())
                checks[f"{role}_configured"] = has_key
                details[f"{role}_configured"] = f"{model.name}:{model.model} key={'yes' if has_key else 'no'}"

        try:
            registry = PluginRegistry(self.plugin_dir)
            manifests = registry.load()
            checks["plugins"] = True
            details["plugins"] = f"{len(manifests)} loaded"
        except PluginValidationError as exc:
            checks["plugins"] = False
            details["plugins"] = str(exc)

        # Real model network checks are intentionally off by default.
        if check_models:
            details["model_network_check"] = "not implemented in doctor v1"

        return DoctorReport(ok=all(checks.values()), checks=checks, details=details)


def main() -> None:
    parser = argparse.ArgumentParser(description="Advanced Agent doctor")
    parser.add_argument("--db", default="runtime/doctor.sqlite")
    parser.add_argument("--config", default=".env.json")
    parser.add_argument("--plugins", default="plugins")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = Doctor(args.db, args.config, args.plugins).run()
    if args.json:
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    else:
        print("OK" if report.ok else "FAILED")
        for name, ok in report.checks.items():
            mark = "✓" if ok else "✗"
            print(f"{mark} {name}: {report.details.get(name, '')}")


if __name__ == "__main__":
    main()
