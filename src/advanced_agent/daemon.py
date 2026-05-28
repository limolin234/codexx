from __future__ import annotations

import argparse
import asyncio
import signal
from contextlib import suppress

from advanced_agent import defaults
from advanced_agent.runtime.loop import RuntimeLoopConfig
from advanced_agent.runtime.service import RuntimeService


async def run_daemon(db: str, config: str | None, tick_interval: float = 1.0, once: bool = False) -> None:
    service = RuntimeService.create(db, config_path=config, loop_config=RuntimeLoopConfig(tick_interval_seconds=tick_interval))
    if once:
        result = await service.loop.tick_once()
        print(f"advanced-agentd tick: fired={result.fired} actions={result.actions}")
        return

    stop_event = asyncio.Event()

    def request_stop() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, request_stop)

    await service.start()
    print(f"advanced-agentd running db={db} config={config} tick={tick_interval}s")
    try:
        await stop_event.wait()
    finally:
        await service.stop()
        print("advanced-agentd stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description="Advanced Agent long-running deterministic runtime daemon.")
    parser.add_argument("--db", default=defaults.default_db())
    parser.add_argument("--config", default=defaults.default_config())
    parser.add_argument("--tick", type=float, default=float(defaults.env_default("ADVANCED_AGENT_DAEMON_TICK", "1.0")))
    parser.add_argument("--once", action="store_true", help="Run one automation tick and exit.")
    args = parser.parse_args()
    asyncio.run(run_daemon(args.db, args.config, tick_interval=args.tick, once=args.once))


if __name__ == "__main__":
    main()
