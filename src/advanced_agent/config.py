from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ModelConfig:
    name: str
    provider: str
    model: str
    base_url: str
    api_key: str | None = None
    api_key_env: str | None = None
    temperature: float = 0.2
    max_tokens: int = 256
    timeout_seconds: float = 30.0

    def resolved_api_key(self) -> str | None:
        if self.api_key:
            return self.api_key
        if self.api_key_env:
            return os.environ.get(self.api_key_env)
        return None


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    roles: dict[str, str] = field(default_factory=dict)
    models: dict[str, ModelConfig] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> "RuntimeConfig":
        return cls()

    @classmethod
    def load(cls, path: str | Path | None) -> "RuntimeConfig":
        if path is None:
            return cls.empty()
        p = Path(path)
        if not p.exists():
            return cls.empty()
        data = json.loads(p.read_text())
        roles = dict(data.get("roles", {}))
        models: dict[str, ModelConfig] = {}
        for name, raw in data.get("models", {}).items():
            models[name] = ModelConfig(
                name=name,
                provider=raw.get("provider", "openai_compatible"),
                model=raw["model"],
                base_url=raw["base_url"],
                api_key=raw.get("api_key"),
                api_key_env=raw.get("api_key_env"),
                temperature=float(raw.get("temperature", 0.2)),
                max_tokens=int(raw.get("max_tokens", 256)),
                timeout_seconds=float(raw.get("timeout_seconds", 30.0)),
            )
        return cls(roles=roles, models=models)

    def model_for_role(self, role: str) -> ModelConfig | None:
        model_name = self.roles.get(role)
        if not model_name or model_name == "default":
            return None
        return self.models.get(model_name)
