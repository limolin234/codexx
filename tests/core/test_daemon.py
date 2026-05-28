import pytest

from advanced_agent.daemon import run_daemon


@pytest.mark.anyio
async def test_daemon_once_runs_tick(tmp_path) -> None:
    await run_daemon(str(tmp_path / "state.sqlite"), None, once=True)
