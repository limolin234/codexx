from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from advanced_agent.audit import AuditAgent
from advanced_agent.events import EventBus, EventStore
from advanced_agent.health import HealthChecker
from advanced_agent.injection_ledger import InjectionLedger
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
from advanced_agent.profile.writer import MajorModelMemoryWriter
from advanced_agent.memory_service import MemoryService
from advanced_agent.memory_maintenance import MemoryMaintenanceWorker
from advanced_agent.semantic_worker import SemanticMaintenanceWorker
from advanced_agent.models import Message, new_id
from advanced_agent.processes import AsyncSubprocessRunner
from advanced_agent.preferences import PreferenceWorker
from advanced_agent.profile.hints import ProfileHintSelector
from advanced_agent.profile.observer import LLMProfileMaintainer
from advanced_agent.stores.audit_store import AuditStore, ControlStore
from advanced_agent.stores.hook_store import HookStore
from advanced_agent import defaults
from advanced_agent.stores.memory_schema import init_memory_schema
from advanced_agent.stores.profile_store import ProfileStore, PromptOverlayStore
from advanced_agent.stores.rawtail_store import RawTailStore, init_rawtail_schema
from advanced_agent.stores.session_store import SessionStore
from advanced_agent.stores.semantic_store import SemanticStore
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
    memory_db: SQLiteStore
    rawtail_db: SQLiteStore
    time: TimeService
    sessions: SessionStore
    tasks: TaskStore
    audit: AuditAgent
    supervisor: Supervisor
    vectors: SQLiteVecStore
    alignment: LLMMemoryAlignment
    memory_indexer: MemoryIndexer
    memory: MemoryService
    capabilities: BackendRegistry
    capability_router: CapabilityRouter
    capability_executor: CapabilityExecutor
    profiles: ProfileStore
    overlays: PromptOverlayStore
    preferences: PreferenceWorker
    profile_hints: ProfileHintSelector
    compactor: ConversationCompactor
    context_builder: ContextBuilder
    context_fork_builder: ContextForkBuilder
    hooks: HookStore
    automation: AutomationEngine
    task_summary_worker: TaskSummaryWorker
    memory_maintenance: MemoryMaintenanceWorker
    semantic_store: SemanticStore
    semantic_maintenance: SemanticMaintenanceWorker
    process_runner: AsyncSubprocessRunner
    codex_worker: CodexTaskWorker
    events: EventBus
    health: HealthChecker
    injection_ledger: InjectionLedger
    workspace: WorkspaceState
    rawtail: RawTailStore

    @classmethod
    def create(
        cls,
        db_path: str | Path,
        config_path: str | Path | None = None,
        *,
        initial_cwd: str | Path | None = None,
        sync_process_cwd: bool = False,
        memory_db_path: str | Path | None = None,
        rawtail_db_path: str | Path | None = None,
        rawtail_max_bytes: int | None = None,
    ) -> "RuntimeApp":
        time = TimeService()
        config = RuntimeConfig.load(config_path)
        router = ModelRouter.from_config(config)
        db_path = Path(db_path)
        db = SQLiteStore(db_path)
        db.init_schema()
        base_dir = db_path.parent.parent if db_path.parent.name == "runtime" else db_path.parent
        memory_db_file = Path(memory_db_path) if memory_db_path is not None else base_dir / defaults.DEFAULT_MEMORY_DB
        rawtail_db_file = Path(rawtail_db_path) if rawtail_db_path is not None else base_dir / defaults.DEFAULT_RAWTAIL_DB
        memory_db = SQLiteStore(memory_db_file, schema_initializer=init_memory_schema)
        memory_db.init_schema()
        rawtail_db = SQLiteStore(rawtail_db_file)
        init_rawtail_schema(rawtail_db)
        event_store = EventStore(db)
        events = EventBus(event_store, time)
        health = HealthChecker(db)
        injection_ledger = InjectionLedger(db, time)
        rawtail = RawTailStore(rawtail_db, max_bytes=rawtail_max_bytes if rawtail_max_bytes is not None else defaults.default_rawtail_max_bytes())
        sessions = SessionStore(db)
        semantic_store = SemanticStore(db)
        tasks = TaskStore(db)
        profiles = ProfileStore(memory_db)
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
        vectors = SQLiteVecStore(memory_db, time)
        capability_executor = CapabilityExecutor(supervisor, tasks, vectors, hooks, time, workspace=workspace)
        alignment = LLMMemoryAlignment(router.client_for("memory_model"), fallback=MemoryAlignment())
        memory_indexer = MemoryIndexer(vectors, alignment, time)
        memory = MemoryService(memory_indexer, vectors)
        profile_hints = ProfileHintSelector(memory)
        context_builder = ContextBuilder(sessions, vectors, memory=memory, profile_selector=profile_hints)
        context_fork_builder = ContextForkBuilder(context_builder)
        profile_maintainer = LLMProfileMaintainer(router.client_for("memory_model"))
        major_memory_writer = MajorModelMemoryWriter(router.client_for("memory_write_model"))
        preferences = PreferenceWorker(sessions, profiles, overlays, time, memory=memory, maintainer=profile_maintainer, major_writer=major_memory_writer)
        compactor = ConversationCompactor(sessions, vectors, alignment, time, memory_indexer=memory_indexer)
        task_summary_worker = TaskSummaryWorker(tasks, time)
        memory_maintenance = MemoryMaintenanceWorker(sessions, memory, preferences, time)
        semantic_maintenance = SemanticMaintenanceWorker(semantic_store, time, router.client_for("memory_model"), memory=memory, approval_model=router.client_for("memory_write_model"))
        automation = AutomationEngine(hooks, preferences, events, time, compactor=compactor, memory_indexer=memory_indexer, task_summary_worker=task_summary_worker, memory_maintenance=memory_maintenance, semantic_maintenance=semantic_maintenance)
        return cls(db=db, memory_db=memory_db, rawtail_db=rawtail_db, time=time, sessions=sessions, tasks=tasks, audit=audit, supervisor=supervisor, vectors=vectors, alignment=alignment, memory_indexer=memory_indexer, memory=memory, capabilities=capabilities, capability_router=capability_router, capability_executor=capability_executor, profiles=profiles, overlays=overlays, preferences=preferences, profile_hints=profile_hints, compactor=compactor, context_builder=context_builder, context_fork_builder=context_fork_builder, hooks=hooks, automation=automation, task_summary_worker=task_summary_worker, memory_maintenance=memory_maintenance, semantic_store=semantic_store, semantic_maintenance=semantic_maintenance, process_runner=process_runner, codex_worker=codex_worker, events=events, health=health, injection_ledger=injection_ledger, workspace=workspace, rawtail=rawtail)

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

    def record_user_message(self, session_id: str, text: str, *, schedule_maintenance: bool = True) -> str:
        """Record external-agent user text without running an internal chat agent."""
        request_id = new_id("req")
        now = self.time.wall_ms()
        self.sessions.append_message(Message(session_id=session_id, request_id=request_id, role="user", content=text, created_at_ms=now))
        self.rawtail.append_chunk(session_id=session_id, source="message", role="user", text=text, request_id=request_id, created_at_ms=now)
        self.events.publish("external.user_message.recorded", "runtime", {"session_id": session_id, "request_id": request_id})
        if schedule_maintenance:
            self.automation.ensure_session_maintenance(session_id, idle_ms=0)
        return request_id

    def raw_tail_lines(self, session_id: str, limit: int = 80, max_chars: int = 800) -> list[str]:
        return self.rawtail.lines(session_id, limit=limit, max_chars=max_chars)

    def close(self) -> None:
        for store in (self.rawtail_db, self.memory_db, self.db):
            try:
                store.optimize()
            except Exception:
                pass
            try:
                store.close()
            except Exception:
                pass

    def chdir(self, path: str):
        return self.workspace.chdir(path)

    def remember(self, text: str, scope: str = "global", type_: str = "note") -> str:
        return self.memory.write(summary=text, content=text, scope=scope, type=type_, source_type="manual", source_id=text[:80]).memory_id

    def search_memory(self, query: str, scope: str | None = None, top_k: int = 5, query_profile: str = "auto"):
        return self.vectors.search(query=query, scope=scope, top_k=top_k, query_profile=query_profile)
