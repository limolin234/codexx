from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from advanced_agent.runtime.app import RuntimeApp
from advanced_agent.runtime.loop import RuntimeLoop, RuntimeLoopConfig


@dataclass(slots=True)
class RuntimeService:
    """Embedding-friendly service wrapper around RuntimeApp + RuntimeLoop."""

    app: RuntimeApp
    loop: RuntimeLoop

    @classmethod
    def create(
        cls,
        db_path: str | Path,
        config_path: str | Path | None = None,
        loop_config: RuntimeLoopConfig | None = None,
    ) -> "RuntimeService":
        app = RuntimeApp.create(db_path, config_path=config_path)
        return cls(app=app, loop=RuntimeLoop(app, loop_config))

    async def start(self) -> None:
        await self.loop.start()

    async def stop(self) -> None:
        await self.loop.stop()

    async def __aenter__(self) -> "RuntimeService":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.stop()
