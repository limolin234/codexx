from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from advanced_agent.agents.interactive import InteractiveAgent
from advanced_agent.agents.main import MainAgent
from advanced_agent.audit import AuditAgent
from advanced_agent.events import EventBus, EventStore
from advanced_agent.health import HealthChecker
from advanced_agent.interrupts import InterruptGate
from advanced_agent.automation import AutomationEngine
from advanced_agent.capabilities import BackendRegistry, CapabilityRouter
from advanced_agent.capability_executor import CapabilityExecutor
from advanced_agent.codex_worker import CodexTaskWorker
from advanced_agent.compaction import ConversationCompactor
from advanced_agent.context_builder import ContextBuilder
from advanced_agent.context_fork import ContextForkBuilder
from advanced_agent.config import RuntimeConfig
from advanced_agent.llm import ModelRouter
from advanced_agent.memory_indexer import MemoryCandidate, MemoryIndexer
from advanced_agent.memory_alignment import LLMMemoryAlignment
from advanced_agent.memory_service import MemoryService
from advanced_agent.models import Message, new_id
from advanced_agent.processes import AsyncSubprocessRunner
from advanced_agent.preferences import PreferenceWorker
from advanced_agent.prompt_builder import PromptBuilder
from advanced_agent.stores.audit_store import AuditStore, ControlStore
from advanced_agent.stores.hook_store import HookStore
from advanced_agent.stores.main_decision_store import MainDecisionStore
from advanced_agent.stores.profile_store import ProfileStore, PromptOverlayStore
from advanced_agent.stores.session_store import SessionStore
from advanced_agent.stores.sqlite_store import SQLiteStore
from advanced_agent.stores.task_store import TaskStore
from advanced_agent.supervisor import Supervisor
from advanced_agent.task_summary_worker import TaskSummaryWorker
from advanced_agent.time_service import TimeService
from advanced_agent.vectors import MemoryAlignment, SQLiteVecStore
from advanced_agent.workspace import WorkspaceState


@dataclass(slots=True)
class RuntimeApp:
    db: SQLiteStore
    time: TimeService
    sessions: SessionStore
    tasks: TaskStore
    audit: AuditAgent
    supervisor: Supervisor
    interactive: InteractiveAgent
    main: MainAgent
    vectors: SQLiteVecStore
    alignment: LLMMemoryAlignment
    memory_indexer: MemoryIndexer
    memory: MemoryService
    capabilities: BackendRegistry
    capability_router: CapabilityRouter
    capability_executor: CapabilityExecutor
    decisions: MainDecisionStore
    profiles: ProfileStore
    overlays: PromptOverlayStore
    preferences: PreferenceWorker
    compactor: ConversationCompactor
    context_builder: ContextBuilder
    context_fork_builder: ContextForkBuilder
    hooks: HookStore
    automation: AutomationEngine
    task_summary_worker: TaskSummaryWorker
    process_runner: AsyncSubprocessRunner
    codex_worker: CodexTaskWorker
    events: EventBus
    health: HealthChecker
    workspace: WorkspaceState
    background_requests: dict[str, asyncio.Task]
    completed_background: dict[str, object]

    @classmethod
    def create(
        cls,
        db_path: str | Path,
        config_path: str | Path | None = None,
        *,
        initial_cwd: str | Path | None = None,
        sync_process_cwd: bool = False,
    ) -> "RuntimeApp":
        time = TimeService()
        config = RuntimeConfig.load(config_path)
        router = ModelRouter.from_config(config)
        db = SQLiteStore(db_path)
        db.init_schema()
        event_store = EventStore(db)
        events = EventBus(event_store, time)
        health = HealthChecker(db)
        sessions = SessionStore(db)
        tasks = TaskStore(db)
        decisions = MainDecisionStore(db)
        profiles = ProfileStore(db)
        overlays = PromptOverlayStore(db)
        hooks = HookStore(db)
        workspace = WorkspaceState(initial_cwd, sync_process_cwd=sync_process_cwd)
        capabilities = BackendRegistry()
        capability_router = CapabilityRouter(capabilities)
        audit_store = AuditStore(db)
        control_store = ControlStore(db)
        audit = AuditAgent(audit_store, time)
        gate = InterruptGate(db, time)
        process_runner = AsyncSubprocessRunner(time)
        codex_worker = CodexTaskWorker(process_runner, tasks, time)
        supervisor = Supervisor(time=time, task_store=tasks, control_store=control_store, audit_agent=audit, interrupt_gate=gate, codex_worker=codex_worker)
        vectors = SQLiteVecStore(db, time)
        capability_executor = CapabilityExecutor(supervisor, tasks, vectors, hooks, time, workspace=workspace)
        alignment = LLMMemoryAlignment(router.client_for("memory_model"), fallback=MemoryAlignment())
        memory_indexer = MemoryIndexer(vectors, alignment, time)
        memory = MemoryService(memory_indexer, vectors)
        context_builder = ContextBuilder(sessions, vectors, memory=memory)
        context_fork_builder = ContextForkBuilder(context_builder)
        prompt_builder = PromptBuilder(context_builder, overlays, capabilities=capabilities)
        interactive = InteractiveAgent(sessions, time, model=router.client_for("interactive_model"), prompt_builder=prompt_builder)
        main = MainAgent(sessions, supervisor, time, decisions=decisions, model=router.client_for("main_model"), prompt_builder=prompt_builder, capability_executor=capability_executor)
        preferences = PreferenceWorker(sessions, profiles, overlays, time)
        compactor = ConversationCompactor(sessions, vectors, alignment, time, memory_indexer=memory_indexer)
        task_summary_worker = TaskSummaryWorker(tasks, time)
        automation = AutomationEngine(hooks, preferences, events, time, compactor=compactor, memory_indexer=memory_indexer, task_summary_worker=task_summary_worker)
        return cls(db=db, time=time, sessions=sessions, tasks=tasks, audit=audit, supervisor=supervisor, interactive=interactive, main=main, vectors=vectors, alignment=alignment, memory_indexer=memory_indexer, memory=memory, capabilities=capabilities, capability_router=capability_router, capability_executor=capability_executor, decisions=decisions, profiles=profiles, overlays=overlays, preferences=preferences, compactor=compactor, context_builder=context_builder, context_fork_builder=context_fork_builder, hooks=hooks, automation=automation, task_summary_worker=task_summary_worker, process_runner=process_runner, codex_worker=codex_worker, events=events, health=health, workspace=workspace, background_requests={}, completed_background={})

    def create_session(self, title: str) -> str:
        session_id = self.sessions.create_session(title=title, now_ms=self.time.wall_ms())
        self.events.publish("session.created", "runtime", {"session_id": session_id, "title": title})
        return session_id

    def default_session(self, title: str = "default") -> str:
        session_id = self.sessions.get_or_create_default_session(title=title, now_ms=self.time.wall_ms())
        self.events.publish("session.default", "runtime", {"session_id": session_id, "title": title})
        return session_id

    def clear_context_before_ms(self, session_id: str, cutoff_ms: int) -> int:
        count = self.sessions.clear_context_before_ms(session_id, cutoff_ms)
        self.events.publish("session.context_cleared_before", "runtime", {"session_id": session_id, "cutoff_ms": cutoff_ms, "messages": count})
        return count

    def rollback_context_to_ms(self, session_id: str, cutoff_ms: int) -> int:
        count = self.sessions.rollback_context_to_ms(session_id, cutoff_ms)
        self.events.publish("session.context_rolled_back", "runtime", {"session_id": session_id, "cutoff_ms": cutoff_ms, "messages": count})
        return count

    def start_user_request(self, session_id: str, text: str) -> tuple[str, object]:
        """Record user input and return the immediate interactive delta."""
        request_id = new_id("req")
        delta = self.interactive.receive_user_message(session_id, request_id, text)
        self.events.publish("interactive.provisional", "interactive", {"session_id": session_id, "request_id": request_id, "delta_id": delta.id})
        self.automation.ensure_session_maintenance(session_id, idle_ms=0)
        return request_id, delta

    def finish_user_request(self, session_id: str, request_id: str, workdir: str):
        """Run main internally, then render its result through interactive."""
        main_delta = self.main.handle_request(session_id, request_id, workdir)
        decision = self.decisions.latest_for_request(session_id, request_id)
        self.events.publish("main.decided", "main", {"session_id": session_id, "request_id": request_id, "decision_id": None if decision is None else decision.id})
        render_text = decision.user_visible_instruction if decision is not None else main_delta.text
        rendered_delta = self.interactive.render_main_reply(session_id, request_id, render_text)
        self.events.publish("interactive.authoritative_render", "interactive", {"session_id": session_id, "request_id": request_id, "delta_id": rendered_delta.id})
        return rendered_delta

    async def finish_user_request_async(self, session_id: str, request_id: str, workdir: str):
        """Async main path for background interactions."""
        main_delta = await self.main.handle_request_async(session_id, request_id, workdir)
        decision = self.decisions.latest_for_request(session_id, request_id)
        self.events.publish("main.decided", "main", {"session_id": session_id, "request_id": request_id, "decision_id": None if decision is None else decision.id})
        render_text = decision.user_visible_instruction if decision is not None else main_delta.text
        rendered_delta = self.interactive.render_main_reply(session_id, request_id, render_text)
        self.events.publish("interactive.authoritative_render", "interactive", {"session_id": session_id, "request_id": request_id, "delta_id": rendered_delta.id})
        return rendered_delta

    async def start_user_request_background(self, session_id: str, text: str, workdir: str) -> tuple[str, object]:
        """Return interactive provisional output now and finish main later.

        This is the first background interaction skeleton. It preserves the
        user-facing contract immediately; the current model client is still
        synchronous internally, so replacing it with an async HTTP backend is a
        later optimization behind the same method boundary.
        """
        request_id, quick = self.start_user_request(session_id, text)
        task = asyncio.create_task(self._finish_user_request_task(session_id, request_id, workdir), name=f"main-request-{request_id}")
        self.background_requests[request_id] = task
        self.events.publish("interaction.background.started", "runtime", {"session_id": session_id, "request_id": request_id})
        return request_id, quick

    async def start_main_request_background(self, session_id: str, text: str, workdir: str | None = None) -> str:
        """Record user input and run main directly in the background.

        This is the preferred CLI path when interactive should not behave like a
        second semantic model. The interactive layer may still render the final
        answer, but it does not produce an independent quick answer.
        """
        request_id = new_id("req")
        self.sessions.append_message(Message(session_id=session_id, request_id=request_id, role="user", content=text, created_at_ms=self.time.wall_ms()))
        task_workdir = workdir or str(self.workspace.cwd)
        task = asyncio.create_task(self._finish_user_request_task(session_id, request_id, task_workdir), name=f"main-direct-{request_id}")
        self.background_requests[request_id] = task
        self.events.publish("interaction.main_direct.started", "runtime", {"session_id": session_id, "request_id": request_id})
        return request_id

    async def wait_user_request(self, request_id: str, timeout_seconds: float | None = None):
        if request_id in self.completed_background:
            return self.completed_background[request_id]
        task = self.background_requests[request_id]
        if timeout_seconds is None:
            return await task
        return await asyncio.wait_for(task, timeout=timeout_seconds)

    async def _finish_user_request_task(self, session_id: str, request_id: str, workdir: str):
        try:
            # Yield once so callers reliably receive the provisional delta
            # before main begins its heavier synchronous work.
            await asyncio.sleep(0)
            result = await self.finish_user_request_async(session_id, request_id, workdir)
            self.completed_background[request_id] = result
            self.events.publish("interaction.background.completed", "runtime", {"session_id": session_id, "request_id": request_id})
            return result
        except Exception as exc:
            self.events.publish("interaction.background.failed", "runtime", {"session_id": session_id, "request_id": request_id, "error": str(exc), "type": type(exc).__name__})
            raise
        finally:
            self.background_requests.pop(request_id, None)

    def handle_user_text(self, session_id: str, text: str, workdir: str | None = None) -> str:
        request_id, _ = self.start_user_request(session_id, text)
        self.finish_user_request(session_id, request_id, workdir or str(self.workspace.cwd))
        return request_id

    def chdir(self, path: str):
        return self.workspace.chdir(path)

    def remember(self, text: str, scope: str = "global", type_: str = "note") -> str:
        return self.memory.write(summary=text, content=text, scope=scope, type=type_, source_type="manual", source_id=text[:80]).memory_id

    def search_memory(self, query: str, scope: str | None = None, top_k: int = 5, query_profile: str = "auto"):
        return self.vectors.search(query=query, scope=scope, top_k=top_k, query_profile=query_profile)
