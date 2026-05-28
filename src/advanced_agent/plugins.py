from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from advanced_agent.errors import ConfigError
from advanced_agent.stores.hook_store import HookStore
from advanced_agent.time_service import TimeService


@dataclass(slots=True)
class PluginHookSpec:
    kind: str
    target: str
    description: str = ""
    default_delay_ms: int = 0
    repeat_ms: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PluginManifest:
    name: str
    version: str
    description: str = ""
    hooks: list[PluginHookSpec] = field(default_factory=list)
    path: Path | None = None


class PluginValidationError(ConfigError):
    pass


class PluginRegistry:
    """Load external plugin manifests and expose hook registration.

    Plugins are intentionally outside the core. The core only schedules and
    fires hooks; plugin agents decide what to read/write when invoked.
    """

    def __init__(self, plugin_dir: str | Path = "plugins") -> None:
        self.plugin_dir = Path(plugin_dir)
        self.manifests: dict[str, PluginManifest] = {}

    def load(self) -> dict[str, PluginManifest]:
        self.manifests.clear()
        if not self.plugin_dir.exists():
            return self.manifests
        for manifest_path in sorted(self.plugin_dir.glob("*/plugin.json")):
            manifest = self._load_manifest(manifest_path)
            self.manifests[manifest.name] = manifest
        return self.manifests

    def _load_manifest(self, path: Path) -> PluginManifest:
        data = json.loads(path.read_text())
        self._validate_manifest_shape(data, path)
        hooks = [
            PluginHookSpec(
                kind=item["kind"],
                target=item.get("target", f"plugin:{data['name']}"),
                description=item.get("description", ""),
                default_delay_ms=int(item.get("default_delay_ms", 0)),
                repeat_ms=item.get("repeat_ms"),
                payload=dict(item.get("payload", {})),
            )
            for item in data.get("hooks", [])
        ]
        manifest = PluginManifest(
            name=data["name"],
            version=data.get("version", "0.1.0"),
            description=data.get("description", ""),
            hooks=hooks,
            path=path.parent,
        )
        self._validate_manifest(manifest)
        return manifest

    def schedule_default_hooks(self, hook_store: HookStore, time: TimeService) -> list[str]:
        now = time.wall_ms()
        ids: list[str] = []
        for manifest in self.manifests.values():
            for hook in manifest.hooks:
                payload = {"plugin": manifest.name, **hook.payload}
                ids.append(
                    hook_store.ensure_unique(
                        hook.kind,
                        target=hook.target,
                        now_ms=now,
                        delay_ms=hook.default_delay_ms,
                        payload=payload,
                        repeat_ms=hook.repeat_ms,
                    )
                )
        return ids

    def _validate_manifest_shape(self, data: dict[str, Any], path: Path) -> None:
        name = data.get("name")
        if not isinstance(name, str) or not name:
            raise PluginValidationError(f"plugin manifest {path} missing non-empty name")
        if any(ch in name for ch in ("/", "\\", "..", " ")):
            raise PluginValidationError(f"plugin {name!r} has unsafe name")
        hooks = data.get("hooks", [])
        if not isinstance(hooks, list):
            raise PluginValidationError(f"plugin {name} hooks must be a list")
        if len(hooks) > 32:
            raise PluginValidationError(f"plugin {name} declares too many hooks")

    def _validate_manifest(self, manifest: PluginManifest) -> None:
        prefix = f"plugin.{manifest.name}."
        for hook in manifest.hooks:
            if not hook.kind.startswith(prefix):
                raise PluginValidationError(f"hook kind {hook.kind!r} must start with {prefix!r}")
            if not hook.target.startswith("plugin:"):
                raise PluginValidationError(f"hook target {hook.target!r} must start with 'plugin:'")
            if hook.repeat_ms is not None and int(hook.repeat_ms) < 1_000:
                raise PluginValidationError("plugin repeat_ms must be >= 1000")
            if len(json.dumps(hook.payload, ensure_ascii=False)) > 4096:
                raise PluginValidationError("plugin hook payload too large")
