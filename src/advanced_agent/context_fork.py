from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from advanced_agent.context_builder import ContextBuilder
from advanced_agent.llm import ChatMessage


@dataclass(slots=True)
class ContextForkSpec:
    parent_session_id: str
    request_id: str
    goal: str
    role: str = "task"
    focus: str | None = None
    max_recent_lines: int = 40
    constraints: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ContextFork:
    spec: ContextForkSpec
    messages: list[ChatMessage]
    cache_key: str
    source_summary: str


class ContextForkBuilder:
    """Build bounded forked context for task/sub agents.

    Forking here means copying only the relevant context resources and goal into
    a stable prompt bundle. It is not a process fork. The cache key is stable for
    the same source lines + goal so provider prompt caching can hit more often.
    """

    def __init__(self, context_builder: ContextBuilder, default_scope: str = "project:advanced_agent") -> None:
        self.context_builder = context_builder
        self.default_scope = default_scope

    def build(self, spec: ContextForkSpec, scope: str | None = None) -> ContextFork:
        built = self.context_builder.build_for_main(spec.parent_session_id, spec.goal, scope=scope or self.default_scope)
        recent = built.recent_messages[-spec.max_recent_lines:]
        memory_lines = [f"- [{hit.type}/{hit.label_kind}] {hit.summary}" for hit in built.retrieved_memories]
        constraints = "\n".join(f"- {item}" for item in spec.constraints) or "- Follow the parent goal; do not invent completed work."
        source_summary = "\n".join([*recent, *memory_lines])
        cache_key = self._cache_key(spec, source_summary)
        system = "\n".join([
            f"You are a forked {spec.role} worker for Advanced Agent.",
            "You receive a bounded copy of parent context. Stay aligned with the parent goal.",
            "Do the assigned work directly; report concise progress and outputs.",
            "Do not expose internal multi-agent architecture to the user-facing channel.",
            "Constraints:",
            constraints,
        ])
        user = "\n".join([
            f"parent_session_id: {spec.parent_session_id}",
            f"request_id: {spec.request_id}",
            f"goal: {spec.goal}",
            f"focus: {spec.focus or '(none)'}",
            "Forked context:",
            source_summary or "(no recent context)",
        ])
        return ContextFork(spec=spec, messages=[ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)], cache_key=cache_key, source_summary=source_summary)

    def _cache_key(self, spec: ContextForkSpec, source_summary: str) -> str:
        stable = "\n".join([spec.parent_session_id, spec.request_id, spec.role, spec.goal, spec.focus or "", source_summary])
        return hashlib.sha256(stable.encode("utf-8")).hexdigest()
