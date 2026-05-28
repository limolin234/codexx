import asyncio
import sys

from advanced_agent.processes import AsyncSubprocessRunner, TailBuffer


def test_tail_buffer_limits() -> None:
    tail = TailBuffer(max_lines=2, max_chars=100)
    tail.append("a\n")
    tail.append("b\n")
    tail.append("c\n")
    assert tail.lines() == ["b\n", "c\n"]


def test_async_subprocess_tail(tmp_path) -> None:
    async def run() -> None:
        runner = AsyncSubprocessRunner()
        outputs = []

        async def on_output(stream: str, text: str) -> None:
            outputs.append((stream, text))

        proc = await runner.start(
            [sys.executable, "-c", "import sys,time; print('hello', flush=True); print('err', file=sys.stderr, flush=True); time.sleep(0.2); print('done', flush=True)"],
            cwd=tmp_path,
            on_output=on_output,
        )
        await asyncio.sleep(0.1)
        assert "hello" in runner.tail(proc.id, "stdout")
        code = await runner.wait(proc.id)
        assert code == 0
        assert "done" in runner.tail(proc.id, "stdout")
        assert "err" in runner.tail(proc.id, "stderr")
        assert outputs

    asyncio.run(run())


def test_async_subprocess_stop(tmp_path) -> None:
    async def run() -> None:
        runner = AsyncSubprocessRunner()
        proc = await runner.start([sys.executable, "-c", "import time; time.sleep(10)"], cwd=tmp_path)
        assert proc.running
        code = await runner.stop(proc.id, timeout_seconds=0.1)
        assert code is not None
        assert not proc.running

    asyncio.run(run())
