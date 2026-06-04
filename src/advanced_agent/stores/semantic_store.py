from __future__ import annotations

import hashlib
from dataclasses import dataclass

from advanced_agent.models import new_id
from advanced_agent.stores.sqlite_store import SQLiteStore, dumps


def semantic_hash(*parts: object) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(str(part).encode("utf-8", errors="replace"))
        h.update(b"\0")
    return h.hexdigest()


@dataclass(slots=True)
class SemanticEvent:
    session_id: str
    seq: int
    kind: str
    text: str
    content_hash: str
    created_at_ms: int
    payload: dict | None = None
    compacted: bool = False
    id: str = ""


@dataclass(slots=True)
class SemanticTask:
    id: str
    session_id: str
    scope: str
    kind: str
    reason: str
    from_seq: int
    to_seq: int
    input_hash: str
    status: str
    attempts: int


@dataclass(slots=True)
class SemanticMemoryCandidate:
    id: str
    session_id: str
    scope: str
    summary_id: str
    candidate_type: str
    summary: str
    content: str
    explanation: str
    evidence_hash: str
    status: str
    importance: float
    confidence: float


class SemanticStore:
    def __init__(self, db: SQLiteStore) -> None:
        self.db = db

    def append_event(self, *, session_id: str, kind: str, text: str, now_ms: int, payload: dict | None = None) -> SemanticEvent | None:
        text = text.strip()
        if not text:
            return None
        content_hash = semantic_hash(kind, text, payload or {})
        last = self.db.query_one(
            "SELECT kind, content_hash FROM semantic_events WHERE session_id=? ORDER BY seq DESC LIMIT 1",
            (session_id,),
        )
        if last is not None and last["kind"] == kind and last["content_hash"] == content_hash:
            return None
        with self.db.transaction():
            row = self.db.query_one("SELECT COALESCE(MAX(seq),0)+1 AS next_seq FROM semantic_events WHERE session_id=?", (session_id,))
            seq = int(row["next_seq"] if row else 1)
            event_id = new_id("sevt")
            self.db.execute(
                """INSERT INTO semantic_events
                (id,session_id,seq,kind,text,payload_json,content_hash,created_at_ms,compacted)
                VALUES(?,?,?,?,?,?,?,?,0)""",
                (event_id, session_id, seq, kind, text, dumps(payload or {}), content_hash, now_ms),
            )
        return SemanticEvent(session_id=session_id, seq=seq, kind=kind, text=text, payload=payload or {}, content_hash=content_hash, created_at_ms=now_ms, id=event_id)

    def active_events(self, session_id: str, limit: int | None = None) -> list[SemanticEvent]:
        sql = "SELECT * FROM semantic_events WHERE session_id=? AND compacted=0 ORDER BY seq"
        params: tuple = (session_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (session_id, limit)
        return [self._event(row) for row in self.db.query_all(sql, params)]

    def event_range(self, session_id: str, from_seq: int, to_seq: int) -> list[SemanticEvent]:
        rows = self.db.query_all(
            "SELECT * FROM semantic_events WHERE session_id=? AND seq BETWEEN ? AND ? ORDER BY seq",
            (session_id, from_seq, to_seq),
        )
        return [self._event(row) for row in rows]

    def active_bytes(self, session_id: str) -> int:
        row = self.db.query_one(
            "SELECT COALESCE(SUM(LENGTH(text)),0) AS bytes FROM semantic_events WHERE session_id=? AND compacted=0",
            (session_id,),
        )
        return int(row["bytes"] if row else 0)

    def unconsumed_user_submits(self, session_id: str) -> int:
        row = self.db.query_one(
            "SELECT COUNT(*) AS c FROM semantic_events WHERE session_id=? AND kind='user_submit' AND compacted=0 AND consumed_by_small_ms IS NULL",
            (session_id,),
        )
        return int(row["c"] if row else 0)

    def mark_small_consumed(self, session_id: str, to_seq: int, now_ms: int) -> None:
        self.db.execute(
            "UPDATE semantic_events SET consumed_by_small_ms=COALESCE(consumed_by_small_ms, ?) WHERE session_id=? AND seq<=?",
            (now_ms, session_id, to_seq),
        )

    def create_task(self, *, session_id: str, scope: str, kind: str, reason: str, from_seq: int, to_seq: int, input_hash: str, now_ms: int) -> str:
        task_id = new_id("semtask")
        self.db.execute(
            """INSERT OR IGNORE INTO semantic_tasks
            (id,session_id,scope,kind,reason,from_seq,to_seq,input_hash,status,attempts,created_at_ms,updated_at_ms)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (task_id, session_id, scope, kind, reason, from_seq, to_seq, input_hash, "pending", 0, now_ms, now_ms),
        )
        row = self.db.query_one(
            "SELECT id FROM semantic_tasks WHERE session_id=? AND kind=? AND from_seq=? AND to_seq=? AND input_hash=?",
            (session_id, kind, from_seq, to_seq, input_hash),
        )
        return str(row["id"] if row else task_id)

    def pending_tasks(self, now_ms: int, *, limit: int = 10, stale_after_ms: int = 5 * 60 * 1000) -> list[SemanticTask]:
        self.db.execute(
            "UPDATE semantic_tasks SET status='pending', updated_at_ms=? WHERE status='running' AND locked_at_ms IS NOT NULL AND locked_at_ms<?",
            (now_ms, now_ms - stale_after_ms),
        )
        rows = self.db.query_all(
            "SELECT * FROM semantic_tasks WHERE status IN ('pending','failed_retryable') ORDER BY created_at_ms LIMIT ?",
            (limit,),
        )
        return [self._task(row) for row in rows]

    def lock_task(self, task_id: str, now_ms: int) -> bool:
        cur = self.db.execute(
            "UPDATE semantic_tasks SET status='running', attempts=attempts+1, locked_at_ms=?, started_at_ms=COALESCE(started_at_ms, ?), updated_at_ms=? WHERE id=? AND status IN ('pending','failed_retryable')",
            (now_ms, now_ms, now_ms, task_id),
        )
        return cur.rowcount > 0

    def complete_compaction_task(self, task: SemanticTask, *, summary: str, source_hash: str, model_name: str | None, prompt_version: str, now_ms: int) -> str:
        summary_id = new_id("semsum")
        with self.db.transaction():
            self.db.execute(
                """INSERT INTO semantic_summaries
                (id,session_id,scope,from_seq,to_seq,summary,source_hash,model_name,prompt_version,created_at_ms,status)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (summary_id, task.session_id, task.scope, task.from_seq, task.to_seq, summary, source_hash, model_name, prompt_version, now_ms, "active"),
            )
            self.db.execute(
                "UPDATE semantic_events SET compacted=1, consumed_by_small_ms=COALESCE(consumed_by_small_ms, ?) WHERE session_id=? AND seq BETWEEN ? AND ?",
                (now_ms, task.session_id, task.from_seq, task.to_seq),
            )
            self.db.execute(
                "UPDATE semantic_tasks SET status='succeeded', finished_at_ms=?, updated_at_ms=?, error=NULL WHERE id=?",
                (now_ms, now_ms, task.id),
            )
        return summary_id

    def create_memory_candidate(
        self,
        *,
        session_id: str,
        scope: str,
        summary_id: str,
        candidate_type: str,
        summary: str,
        content: str,
        explanation: str,
        evidence_hash: str,
        importance: float,
        confidence: float,
        now_ms: int,
    ) -> str:
        candidate_id = new_id("semcand")
        self.db.execute(
            """INSERT OR IGNORE INTO semantic_memory_candidates
            (id,session_id,scope,summary_id,candidate_type,summary,content,explanation,evidence_hash,status,importance,confidence,created_at_ms,updated_at_ms)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (candidate_id, session_id, scope, summary_id, candidate_type, summary, content, explanation, evidence_hash, "pending", importance, confidence, now_ms, now_ms),
        )
        row = self.db.query_one(
            "SELECT id FROM semantic_memory_candidates WHERE summary_id=? AND candidate_type=? AND evidence_hash=?",
            (summary_id, candidate_type, evidence_hash),
        )
        return str(row["id"] if row else candidate_id)

    def pending_candidates(self, *, limit: int = 10) -> list[SemanticMemoryCandidate]:
        rows = self.db.query_all(
            "SELECT * FROM semantic_memory_candidates WHERE status IN ('pending','failed_retryable') ORDER BY created_at_ms LIMIT ?",
            (limit,),
        )
        return [self._candidate(row) for row in rows]

    def lock_candidate(self, candidate_id: str, now_ms: int) -> bool:
        cur = self.db.execute(
            "UPDATE semantic_memory_candidates SET status='running_approval', updated_at_ms=? WHERE id=? AND status IN ('pending','failed_retryable')",
            (now_ms, candidate_id),
        )
        return cur.rowcount > 0

    def complete_candidate(self, candidate_id: str, *, status: str, now_ms: int, approved_memory_id: str | None = None, model_name: str | None = None, error: str | None = None) -> None:
        self.db.execute(
            "UPDATE semantic_memory_candidates SET status=?, approved_memory_id=?, model_name=?, error=?, updated_at_ms=? WHERE id=?",
            (status, approved_memory_id, model_name, error, now_ms, candidate_id),
        )

    def fail_task(self, task_id: str, error: str, now_ms: int, *, retryable: bool = True) -> None:
        self.db.execute(
            "UPDATE semantic_tasks SET status=?, error=?, updated_at_ms=? WHERE id=?",
            ("failed_retryable" if retryable else "failed_permanent", error[:1000], now_ms, task_id),
        )

    def latest_summary(self, session_id: str, scope: str) -> str | None:
        row = self.db.query_one(
            "SELECT summary FROM semantic_summaries WHERE session_id=? AND scope=? AND status='active' ORDER BY to_seq DESC, created_at_ms DESC LIMIT 1",
            (session_id, scope),
        )
        return str(row["summary"]) if row else None

    def _event(self, row) -> SemanticEvent:
        return SemanticEvent(
            id=row["id"],
            session_id=row["session_id"],
            seq=int(row["seq"]),
            kind=row["kind"],
            text=row["text"],
            content_hash=row["content_hash"],
            created_at_ms=int(row["created_at_ms"]),
            compacted=bool(row["compacted"]),
        )

    def _task(self, row) -> SemanticTask:
        return SemanticTask(
            id=row["id"],
            session_id=row["session_id"],
            scope=row["scope"],
            kind=row["kind"],
            reason=row["reason"],
            from_seq=int(row["from_seq"]),
            to_seq=int(row["to_seq"]),
            input_hash=row["input_hash"],
            status=row["status"],
            attempts=int(row["attempts"]),
        )

    def _candidate(self, row) -> SemanticMemoryCandidate:
        return SemanticMemoryCandidate(
            id=row["id"],
            session_id=row["session_id"],
            scope=row["scope"],
            summary_id=row["summary_id"],
            candidate_type=row["candidate_type"],
            summary=row["summary"],
            content=row["content"],
            explanation=row["explanation"],
            evidence_hash=row["evidence_hash"],
            status=row["status"],
            importance=float(row["importance"]),
            confidence=float(row["confidence"]),
        )
