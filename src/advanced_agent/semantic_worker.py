from __future__ import annotations

from dataclasses import dataclass

import json

from advanced_agent.llm import ChatMessage, LLMError, OpenAICompatibleClient
from advanced_agent.memory_service import MemoryService
from advanced_agent.stores.semantic_store import SemanticEvent, SemanticMemoryCandidate, SemanticStore, semantic_hash
from advanced_agent.time_service import TimeService


SEMANTIC_COMPACT_PROMPT_VERSION = "semantic_compact_v1"
SEMANTIC_APPROVE_PROMPT_VERSION = "semantic_memory_approve_v1"
SEMANTIC_MEMORY_TOOL_NAME = "semantic_memory_decision"


@dataclass(slots=True)
class SemanticMaintenanceResult:
    tasks_processed: int = 0
    summaries_created: int = 0
    tasks_created: int = 0
    candidates_created: int = 0
    candidates_processed: int = 0
    memories_written: int = 0
    reason: str = "skipped"


class SemanticMaintenanceWorker:
    def __init__(
        self,
        store: SemanticStore,
        time: TimeService,
        model: OpenAICompatibleClient | None = None,
        memory: MemoryService | None = None,
        approval_model: OpenAICompatibleClient | None = None,
        *,
        compact_threshold_bytes: int = 768 * 1024,
        keep_tail_ratio: float = 0.25,
    ) -> None:
        self.store = store
        self.time = time
        self.model = model
        self.memory = memory
        self.approval_model = approval_model
        self.compact_threshold_bytes = compact_threshold_bytes
        self.keep_tail_ratio = keep_tail_ratio

    def ensure_compaction_task(self, *, session_id: str, scope: str, reason: str, force: bool = False) -> str | None:
        events = self.store.active_events(session_id)
        if not events:
            return None
        active_bytes = sum(len(event.text.encode("utf-8")) for event in events)
        user_submits = sum(1 for event in events if event.kind == "user_submit")
        should_compact = force or active_bytes >= self.compact_threshold_bytes or user_submits >= 3
        if not should_compact:
            return None
        selected = self._select_compaction_window(events, force=force)
        if not selected:
            return None
        from_seq = selected[0].seq
        to_seq = selected[-1].seq
        input_hash = semantic_hash("semantic_compact", session_id, scope, from_seq, to_seq, [event.content_hash for event in selected], SEMANTIC_COMPACT_PROMPT_VERSION)
        return self.store.create_task(
            session_id=session_id,
            scope=scope,
            kind="semantic_compact",
            reason=reason,
            from_seq=from_seq,
            to_seq=to_seq,
            input_hash=input_hash,
            now_ms=self.time.wall_ms(),
        )

    def run(self, *, session_id: str | None = None, scope: str = "project:advanced_agent", reason: str = "scheduled", force: bool = False, limit: int = 10) -> SemanticMaintenanceResult:
        result = SemanticMaintenanceResult(reason=reason)
        if session_id:
            if self.ensure_compaction_task(session_id=session_id, scope=scope, reason=reason, force=force) is not None:
                result.tasks_created += 1
        now = self.time.wall_ms()
        for task in self.store.pending_tasks(now, limit=limit):
            if not self.store.lock_task(task.id, self.time.wall_ms()):
                continue
            try:
                events = self.store.event_range(task.session_id, task.from_seq, task.to_seq)
                summary, model_name = self._summarize(task.scope, events)
                source_hash = semantic_hash(task.input_hash, summary, model_name or "deterministic")
                summary_id = self.store.complete_compaction_task(
                    task,
                    summary=summary,
                    source_hash=source_hash,
                    model_name=model_name,
                    prompt_version=SEMANTIC_COMPACT_PROMPT_VERSION,
                    now_ms=self.time.wall_ms(),
                )
                if task.reason in {"session_close", "interrupt"}:
                    self._create_candidate_from_summary(task.session_id, task.scope, summary_id=summary_id, summary=summary, evidence_hash=task.input_hash)
                    result.candidates_created += 1
                result.summaries_created += 1
            except Exception as exc:  # pragma: no cover - defensive runtime path
                self.store.fail_task(task.id, f"{type(exc).__name__}: {exc}", self.time.wall_ms(), retryable=True)
            result.tasks_processed += 1
        approved, written = self._process_candidates(limit=limit)
        result.candidates_processed += approved
        result.memories_written += written
        return result

    def _create_candidate_from_summary(self, session_id: str, scope: str, *, summary_id: str | None, summary: str, evidence_hash: str) -> str | None:
        if not summary_id:
            return None
        headline = self._headline(summary)
        if not headline:
            return None
        return self.store.create_memory_candidate(
            session_id=session_id,
            scope=scope,
            summary_id=summary_id,
            candidate_type="handoff",
            summary=headline[:280],
            content=summary[:4000],
            explanation="Small-model/deterministic rolling summary from cleaned TTY semantic events; candidate requires approval before durable memory write.",
            evidence_hash=evidence_hash,
            importance=0.65,
            confidence=0.7,
            now_ms=self.time.wall_ms(),
        )

    def _process_candidates(self, *, limit: int) -> tuple[int, int]:
        processed = 0
        written = 0
        for candidate in self.store.pending_candidates(limit=limit):
            if not self.store.lock_candidate(candidate.id, self.time.wall_ms()):
                continue
            processed += 1
            if self.approval_model is None or self.memory is None:
                self.store.complete_candidate(candidate.id, status="awaiting_approval_model", now_ms=self.time.wall_ms(), error="approval_model_or_memory_not_configured")
                continue
            try:
                decision = self._approve_candidate(candidate)
                if not decision.get("approve"):
                    self.store.complete_candidate(candidate.id, status="rejected", now_ms=self.time.wall_ms(), model_name=self.approval_model.config.model, error=str(decision.get("reason", "rejected"))[:1000])
                    continue
                memory_type = str(decision.get("type") or candidate.candidate_type or "handoff")
                result = self.memory.write(
                    summary=str(decision.get("summary") or candidate.summary)[:280],
                    content=str(decision.get("content") or candidate.content)[:4000],
                    scope=candidate.scope,
                    type=memory_type,
                    source_type="semantic_memory",
                    source_id=f"semantic:{candidate.id}:{candidate.evidence_hash}",
                    importance=float(decision.get("importance", candidate.importance)),
                    confidence=float(decision.get("confidence", candidate.confidence)),
                    source_strength="model_summary",
                    stability=str(decision.get("stability") or "normal"),
                    metadata={"semantic_candidate_id": candidate.id, "summary_id": candidate.summary_id, "approval_prompt_version": SEMANTIC_APPROVE_PROMPT_VERSION},
                    agent_role="memory",
                )
                self.store.complete_candidate(candidate.id, status="succeeded", now_ms=self.time.wall_ms(), approved_memory_id=result.memory_id, model_name=self.approval_model.config.model)
                written += 1 if result.created else 0
            except Exception as exc:  # pragma: no cover - defensive runtime path
                self.store.complete_candidate(candidate.id, status="failed_retryable", now_ms=self.time.wall_ms(), model_name=self.approval_model.config.model, error=f"{type(exc).__name__}: {exc}"[:1000])
        return processed, written

    def _approve_candidate(self, candidate: SemanticMemoryCandidate) -> dict:
        assert self.approval_model is not None
        response = self.approval_model.chat_complete(
            [
                ChatMessage(role="system", content=(
                    "You are the conservative durable-memory gatekeeper. "
                    "Approve only if the candidate is useful, non-duplicative, and grounded in the summary/explanation. "
                    "Reject weak preferences, assistant-only claims, or noisy session details. Use the tool only."
                )),
                ChatMessage(role="user", content=json.dumps({
                    "candidate": {
                        "id": candidate.id,
                        "scope": candidate.scope,
                        "type": candidate.candidate_type,
                        "summary": candidate.summary,
                        "content": candidate.content,
                        "explanation": candidate.explanation,
                        "importance": candidate.importance,
                        "confidence": candidate.confidence,
                    },
                    "existing_related_memories": self._existing_related_memories(candidate),
                    "instruction": "Approve only durable project handoffs, decisions, preferences, verified outcomes, or stable workflow habits.",
                }, ensure_ascii=False, sort_keys=True)),
            ],
            tools=[self._approval_tool_schema()],
            tool_choice={"type": "function", "function": {"name": SEMANTIC_MEMORY_TOOL_NAME}},
        )
        for call in response.tool_calls:
            if call.name == SEMANTIC_MEMORY_TOOL_NAME:
                return json.loads(call.arguments or "{}")
        return {"approve": False, "reason": "no_tool_call"}

    def _existing_related_memories(self, candidate: SemanticMemoryCandidate) -> list[dict]:
        if self.memory is None:
            return []
        try:
            records = self.memory.search(candidate.summary, scope=candidate.scope, top_k=5)
        except Exception:
            return []
        return [
            {
                "memory_id": record.memory_id,
                "type": record.type,
                "summary": record.summary,
                "content": (record.content or "")[:800],
                "confidence": record.confidence,
                "importance": record.importance,
            }
            for record in records
        ]

    def _approval_tool_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": SEMANTIC_MEMORY_TOOL_NAME,
                "description": "Approve or reject one semantic durable-memory candidate.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "approve": {"type": "boolean"},
                        "reason": {"type": "string"},
                        "type": {"type": "string", "enum": ["handoff", "decision", "preference", "workflow_habit", "verification", "note"]},
                        "summary": {"type": "string"},
                        "content": {"type": "string"},
                        "importance": {"type": "number"},
                        "confidence": {"type": "number"},
                        "stability": {"type": "string"},
                    },
                    "required": ["approve", "reason"],
                    "additionalProperties": False,
                },
            },
        }

    def _select_compaction_window(self, events: list[SemanticEvent], *, force: bool) -> list[SemanticEvent]:
        if force:
            return events
        keep = max(1, int(len(events) * self.keep_tail_ratio))
        return events[:-keep] if len(events) > keep else events

    def _summarize(self, scope: str, events: list[SemanticEvent]) -> tuple[str, str | None]:
        transcript = self._transcript(events)
        previous = self.store.latest_summary(events[0].session_id, scope) if events else None
        if self.model is not None and transcript.strip():
            try:
                raw = self.model.chat([
                    ChatMessage(role="system", content=(
                        "You compress cleaned terminal dialogue for an agent runtime. "
                        "Preserve user requests, corrections, architecture decisions, files changed, tool/test conclusions, and unresolved next steps. "
                        "Do not create long-term memory claims; this is only a rolling session summary. "
                        "Return concise plain text."
                    )),
                    ChatMessage(role="user", content=self._model_input(scope, previous, transcript)),
                ])
                text = raw.strip()
                if text:
                    return text[:4000], self.model.config.model
            except (LLMError, ValueError, TypeError):
                pass
        return self._deterministic_summary(previous, events), None

    def _model_input(self, scope: str, previous: str | None, transcript: str) -> str:
        parts = [f"scope: {scope}"]
        if previous:
            parts.extend(["previous rolling summary:", previous[:2000]])
        parts.extend(["new cleaned semantic events:", transcript[-12000:]])
        return "\n\n".join(parts)

    def _transcript(self, events: list[SemanticEvent]) -> str:
        return "\n".join(f"[{event.seq} {event.kind}] {event.text}" for event in events)

    def _deterministic_summary(self, previous: str | None, events: list[SemanticEvent]) -> str:
        lines: list[str] = []
        if previous:
            lines.append("Previous summary: " + previous[:1200])
        lines.append(f"Compressed semantic events {events[0].seq if events else 0}-{events[-1].seq if events else 0}:")
        for event in events[-40:]:
            text = " ".join(event.text.split())
            lines.append(f"- [{event.seq} {event.kind}] {text[:240]}")
        return "\n".join(lines)[:4000]

    def _headline(self, summary: str) -> str:
        for line in summary.splitlines():
            text = line.strip(" -")
            if text and not text.lower().startswith("previous summary"):
                return text
        return summary.strip()[:280]
