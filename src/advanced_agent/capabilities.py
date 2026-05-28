from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class LatencyClass(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskClass(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class Capability:
    name: str
    backend: str
    description: str
    latency: LatencyClass
    risk: RiskClass
    requires_task: bool = False
    requires_audit: bool = False
    tags: tuple[str, ...] = ()


@dataclass(slots=True)
class RouteDecision:
    capability: Capability
    reason: str


class BackendRegistry:
    """Abstract backend/capability registry.

    Main agent should see this abstract capability view, not every low-level
    Codex tool or skill.
    """

    def __init__(self) -> None:
        self.capabilities: dict[str, Capability] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        for cap in (
            Capability("task_state", "core", "Read current task state.", LatencyClass.LOW, RiskClass.LOW, tags=("task", "read")),
            Capability("task_list", "core", "List recent managed tasks when task id is unknown.", LatencyClass.LOW, RiskClass.LOW, tags=("task", "read")),
            Capability("task_tail", "core", "Read recent task stdout/stderr tail without interrupting it.", LatencyClass.LOW, RiskClass.LOW, tags=("task", "read")),
            Capability("task_history", "core", "Read task state, output chunks, events, and summaries.", LatencyClass.LOW, RiskClass.LOW, tags=("task", "read")),
            Capability("project_info", "core", "Read current runtime working directory and project root.", LatencyClass.LOW, RiskClass.LOW, tags=("runtime", "read")),
            Capability("workdir_chdir", "core", "Change the agent runtime working directory like a shell built-in cd.", LatencyClass.LOW, RiskClass.LOW, tags=("runtime", "cwd", "write")),
            Capability("memory_search", "core", "Search vector memory.", LatencyClass.LOW, RiskClass.LOW, tags=("memory", "read")),
            Capability("hook_schedule", "core", "Schedule runtime hooks.", LatencyClass.LOW, RiskClass.LOW, tags=("hook", "schedule")),
            Capability("interrupt_request", "core", "Submit stop/cancel/pause requests.", LatencyClass.LOW, RiskClass.MEDIUM, tags=("control",)),
            Capability("spawn_task", "core", "Create bounded managed tasks; heavy execution routes to task backend.", LatencyClass.LOW, RiskClass.MEDIUM, requires_audit=True, tags=("task", "create")),
            Capability("code_editing", "codex-cli", "Delegate code/file editing to Codex task worker.", LatencyClass.HIGH, RiskClass.MEDIUM, requires_task=True, requires_audit=True, tags=("code", "file", "shell")),
            Capability("project_analysis", "codex-cli", "Delegate deep project analysis to Codex task worker.", LatencyClass.HIGH, RiskClass.MEDIUM, requires_task=True, requires_audit=True, tags=("analysis", "project")),
            Capability("document_generation", "codex-cli", "Delegate long document generation to Codex task worker.", LatencyClass.HIGH, RiskClass.LOW, requires_task=True, requires_audit=False, tags=("document",)),
            Capability("plugin_hook", "plugin", "Schedule external plugin hook.", LatencyClass.MEDIUM, RiskClass.MEDIUM, requires_task=False, requires_audit=True, tags=("plugin",)),
        ):
            self.register(cap)

    def register(self, capability: Capability) -> None:
        self.capabilities[capability.name] = capability

    def list_for_prompt(self, max_items: int = 20) -> str:
        rows = []
        for cap in list(self.capabilities.values())[:max_items]:
            rows.append(
                f"- {cap.name}: backend={cap.backend}, latency={cap.latency.value}, risk={cap.risk.value}, "
                f"requires_task={cap.requires_task}, requires_audit={cap.requires_audit}. {cap.description}"
            )
        return "\n".join(rows)


class CapabilityRouter:
    """Small deterministic router for first-pass capability selection."""

    def __init__(self, registry: BackendRegistry) -> None:
        self.registry = registry

    def route(self, intent: str) -> RouteDecision:
        text = intent.lower()
        if any(key in text for key in ("状态", "进度", "tail", "history", "历史")):
            return self._decision("task_state", "progress/history query should use low-latency core task state")
        if any(key in text for key in ("记忆", "偏好", "画像", "memory", "search")):
            return self._decision("memory_search", "memory/profile query should use core vector memory")
        if any(key in text for key in ("定时", "hook", "唤醒", "提醒")):
            return self._decision("hook_schedule", "time/hook request should use core hook scheduler")
        if any(key in text for key in ("代码", "修改", "文件", "测试", "debug", "实现")):
            return self._decision("code_editing", "code/file/shell-heavy work should be delegated to Codex")
        if any(key in text for key in ("总结", "文档", "报告")):
            return self._decision("document_generation", "long generation can be delegated to Codex or document worker")
        return self._decision("project_analysis", "default non-trivial work goes to Codex-backed project analysis")

    def _decision(self, name: str, reason: str) -> RouteDecision:
        return RouteDecision(self.registry.capabilities[name], reason)
