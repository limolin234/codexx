import asyncio

from advanced_agent.hooks import HookKind
from advanced_agent.runtime.loop import RuntimeLoop, RuntimeLoopConfig
from advanced_agent.runtime.service import RuntimeService
from advanced_agent.runtime.app import RuntimeApp


def test_runtime_loop_tick_fires_due_hook(tmp_path) -> None:
    async def run() -> None:
        app = RuntimeApp.create(tmp_path / "state.sqlite")
        app.hooks.schedule_in(HookKind.MEMORY_INDEX, target="memory:indexer", now_ms=app.time.wall_ms(), delay_ms=0, payload={"text": "runtime loop indexes memory", "scope": "project:loop"})
        loop = RuntimeLoop(app, RuntimeLoopConfig(tick_interval_seconds=0.01))
        result = await loop.tick_once()
        assert result.fired == 1
        assert app.search_memory("runtime loop", scope="project:loop")
        events = app.events.store.recent(20)
        assert any(event.type == "runtime.tick" for event in events)

    asyncio.run(run())


def test_runtime_service_start_stop(tmp_path) -> None:
    async def run() -> None:
        service = RuntimeService.create(tmp_path / "state.sqlite", loop_config=RuntimeLoopConfig(tick_interval_seconds=0.01, publish_idle_ticks=True))
        await service.start()
        assert service.loop.running
        await asyncio.sleep(0.03)
        await service.stop()
        assert not service.loop.running
        events = service.app.events.store.recent(20)
        types = [event.type for event in events]
        assert "runtime.loop.started" in types
        assert "runtime.loop.stopped" in types

    asyncio.run(run())
