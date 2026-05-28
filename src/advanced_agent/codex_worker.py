from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from advanced_agent.processes import AsyncSubprocessRunner, ManagedProcess
from advanced_agent.stores.task_store import TaskStore
from advanced_agent.time_service import TimeService


@dataclass(slots=True)
class CodexCommandSpec:
    prompt: str
    workdir: str | Path
    sandbox: str = "workspace-write"
    approval: str = "on-request"
    skip_git_repo_check: bool = True
    extra_args: Sequence[str] = field(default_factory=tuple)


@dataclass(slots=True)
class CodexParsedEvent:
    type: str
    payload: dict[str, Any]
    raw: str


class CodexJsonlParser:
    """Parse Codex `exec --json` JSONL into normalized task events."""

    def parse_line(self, line: str) -> CodexParsedEvent | None:
        stripped = line.strip()
        if not stripped:
            return None
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            return CodexParsedEvent(type="codex.raw_text", payload={"text": stripped}, raw=line)

        event_type = data.get("type", "codex.unknown")
        if event_type == "item.completed":
            item = data.get("item", {})
            item_type = item.get("type", "unknown")
            return CodexParsedEvent(type=f"codex.item.{item_type}", payload=data, raw=line)
        return CodexParsedEvent(type=f"codex.{event_type}", payload=data, raw=line)


@dataclass(slots=True)
class CodexTaskHandle:
    task_id: str
    process: ManagedProcess
    latest_agent_message: str | None = None
    usage: dict[str, Any] | None = None


class CodexTaskWorker:
    """Codex CLI task backend wrapper.

    This layer owns Codex JSONL parsing, while AsyncSubprocessRunner owns raw
    process and tail behavior.
    """

    def __init__(self, runner: AsyncSubprocessRunner, task_store: TaskStore, time: TimeService, parser: CodexJsonlParser | None = None) -> None:
        self.runner = runner
        self.task_store = task_store
        self.time = time
        self.parser = parser or CodexJsonlParser()

    def build_command(self, spec: CodexCommandSpec) -> list[str]:
        command = ["codex", "exec", "--json"]
        if spec.skip_git_repo_check:
            command.append("--skip-git-repo-check")
        command.extend(["-C", str(spec.workdir), "--sandbox", spec.sandbox, "--ask-for-approval", spec.approval])
        command.extend(spec.extra_args)
        command.append(spec.prompt)
        return command

    async def start(self, task_id: str, prompt: str, workdir: str | Path, command: Sequence[str] | None = None, spec: CodexCommandSpec | None = None) -> CodexTaskHandle:
        codex_spec = spec or CodexCommandSpec(prompt=prompt, workdir=workdir)
        cmd = list(command) if command is not None else self.build_command(codex_spec)
        handle_box: dict[str, CodexTaskHandle] = {}
        early_state: dict[str, Any] = {}

        async def on_output(stream: str, text: str) -> None:
            now = self.time.wall_ms()
            self.task_store.append_output(task_id, stream, text, now)
            if stream == "stdout":
                parsed = self.parser.parse_line(text)
                if parsed is not None:
                    self._record_parsed_event(task_id, parsed, now, handle_box.get("handle"), early_state)

        self.task_store.update_task_state(task_id, "running", self.time.wall_ms(), stage="codex", summary="Codex task process started.")
        process = await self.runner.start(cmd, cwd=workdir, on_output=on_output)
        handle = CodexTaskHandle(task_id=task_id, process=process, latest_agent_message=early_state.get("latest_agent_message"), usage=early_state.get("usage"))
        handle_box["handle"] = handle
        return handle

    async def wait(self, handle: CodexTaskHandle) -> int:
        code = await self.runner.wait(handle.process.id)
        status = "completed" if code == 0 else "failed"
        self.task_store.update_task_state(handle.task_id, status, self.time.wall_ms(), summary=f"Codex task exited with code {code}.")
        self.task_store.append_event(handle.task_id, "codex.process.exit", {"returncode": code}, self.time.wall_ms(), self.time.monotonic_ms())
        if handle.latest_agent_message:
            self.task_store.append_summary(handle.task_id, "final", handle.latest_agent_message, [], [], self.time.wall_ms())
        return code

    def _record_parsed_event(self, task_id: str, parsed: CodexParsedEvent, now_ms: int, handle: CodexTaskHandle | None = None, early_state: dict[str, Any] | None = None) -> None:
        self.task_store.append_event(task_id, parsed.type, parsed.payload, now_ms, self.time.monotonic_ms())
        if parsed.type == "codex.item.agent_message":
            item = parsed.payload.get("item", {})
            text = item.get("text") or item.get("content") or ""
            if text:
                if handle is not None:
                    handle.latest_agent_message = text
                elif early_state is not None:
                    early_state["latest_agent_message"] = text
                self.task_store.append_summary(task_id, "codex_agent_message", text[:1200], [], [], now_ms)
        elif parsed.type == "codex.turn.completed":
            usage = parsed.payload.get("usage", {})
            if handle is not None:
                handle.usage = usage
            elif early_state is not None:
                early_state["usage"] = usage
            if usage:
                self.task_store.append_summary(task_id, "usage", f"Codex usage: {usage}", [], [], now_ms)
        elif "tool" in parsed.type or "function_call" in parsed.type:
            self.task_store.update_task_state(task_id, "running", now_ms, stage="tool", summary=f"Codex event: {parsed.type}")
