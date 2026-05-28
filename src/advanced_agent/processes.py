from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Sequence

from advanced_agent.models import new_id
from advanced_agent.time_service import TimeService

OutputCallback = Callable[[str, str], Awaitable[None] | None]


@dataclass(slots=True)
class TailBuffer:
    max_lines: int = 200
    max_chars: int = 64_000
    _lines: deque[str] = field(default_factory=deque)
    _chars: int = 0

    def append(self, text: str) -> None:
        if not text:
            return
        self._lines.append(text)
        self._chars += len(text)
        while len(self._lines) > self.max_lines or self._chars > self.max_chars:
            removed = self._lines.popleft()
            self._chars -= len(removed)

    def lines(self, limit: int | None = None) -> list[str]:
        items = list(self._lines)
        if limit is not None:
            return items[-limit:]
        return items

    def text(self, limit: int | None = None) -> str:
        return "".join(self.lines(limit))


@dataclass(slots=True)
class ManagedProcess:
    command: Sequence[str]
    cwd: str | None
    process: asyncio.subprocess.Process
    started_at_ms: int
    id: str = field(default_factory=lambda: new_id("proc"))
    stdout_tail: TailBuffer = field(default_factory=TailBuffer)
    stderr_tail: TailBuffer = field(default_factory=TailBuffer)
    returncode: int | None = None
    stopped_at_ms: int | None = None

    @property
    def running(self) -> bool:
        return self.returncode is None and self.process.returncode is None

    def tail(self, stream: str = "both", limit: int | None = None) -> str:
        if stream == "stdout":
            return self.stdout_tail.text(limit)
        if stream == "stderr":
            return self.stderr_tail.text(limit)
        return self.stdout_tail.text(limit) + self.stderr_tail.text(limit)


class AsyncSubprocessRunner:
    """Non-blocking subprocess runner with live tail buffers.

    This is the foundation for CodexTaskWorker and other host-level workers.
    It intentionally runs on the host, not inside Docker. Sandboxing/permission
    policy should be layered above it.
    """

    def __init__(self, time: TimeService | None = None) -> None:
        self.time = time or TimeService()
        self.processes: dict[str, ManagedProcess] = {}
        self._reader_tasks: dict[str, list[asyncio.Task]] = {}

    async def start(self, command: Sequence[str], cwd: str | Path | None = None, on_output: OutputCallback | None = None) -> ManagedProcess:
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(cwd) if cwd is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        managed = ManagedProcess(command=tuple(command), cwd=str(cwd) if cwd is not None else None, process=proc, started_at_ms=self.time.wall_ms())
        self.processes[managed.id] = managed
        self._reader_tasks[managed.id] = [
            asyncio.create_task(self._read_stream(managed, "stdout", on_output)),
            asyncio.create_task(self._read_stream(managed, "stderr", on_output)),
            asyncio.create_task(self._wait(managed)),
        ]
        return managed

    async def _read_stream(self, managed: ManagedProcess, stream: str, on_output: OutputCallback | None) -> None:
        pipe = managed.process.stdout if stream == "stdout" else managed.process.stderr
        assert pipe is not None
        while True:
            data = await pipe.readline()
            if not data:
                break
            text = data.decode("utf-8", errors="replace")
            if stream == "stdout":
                managed.stdout_tail.append(text)
            else:
                managed.stderr_tail.append(text)
            if on_output is not None:
                result = on_output(stream, text)
                if asyncio.iscoroutine(result):
                    await result

    async def _wait(self, managed: ManagedProcess) -> None:
        managed.returncode = await managed.process.wait()
        managed.stopped_at_ms = self.time.wall_ms()

    def get(self, process_id: str) -> ManagedProcess | None:
        return self.processes.get(process_id)

    def tail(self, process_id: str, stream: str = "both", limit: int | None = None) -> str:
        proc = self.processes[process_id]
        return proc.tail(stream=stream, limit=limit)

    async def wait(self, process_id: str) -> int:
        managed = self.processes[process_id]
        code = await managed.process.wait()
        managed.returncode = code
        managed.stopped_at_ms = self.time.wall_ms()
        tasks = self._reader_tasks.get(process_id, [])
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return code

    async def stop(self, process_id: str, timeout_seconds: float = 5.0) -> int:
        managed = self.processes[process_id]
        if managed.process.returncode is None:
            managed.process.terminate()
            try:
                await asyncio.wait_for(managed.process.wait(), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                managed.process.kill()
                await managed.process.wait()
        managed.returncode = managed.process.returncode
        managed.stopped_at_ms = self.time.wall_ms()
        await asyncio.gather(*self._reader_tasks.get(process_id, []), return_exceptions=True)
        return managed.returncode if managed.returncode is not None else -1
