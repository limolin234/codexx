from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

from advanced_agent.models import new_id
from advanced_agent.stores.sqlite_store import SQLiteStore, dumps


def semantic_hash(*parts: object) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(str(part).encode("utf-8", errors="replace"))
        h.update(b"\0")
    return h.hexdigest()


SUMMARY_BLOCK_MAX_CHARS = 4000
SUMMARY_ROLLUP_STATUS = "rolled_up"
SUMMARY_ROLLUP_PROMPT_VERSION = "semantic_compact_v2_cache_ledger_rollup"
SUMMARY_ROLLUP_HEADER = "ROLLED_UP_PRIOR_SUMMARY"
SUMMARY_LEDGER_MIN_BUDGET_CHARS = 1000
SUMMARY_ROLLUP_SUFFIX_BUDGET_RATIO = 0.55
SUMMARY_ROLLUP_ANCHOR_BUDGET_RATIO = 0.30
SUMMARY_ROLLUP_ANCHOR_MAX_CHARS = 6000


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

    def summary_blocks(self, session_id: str, scope: str, *, limit: int = 24, max_chars: int = 24000, now_ms: int | None = None) -> list[str]:
        """Return active rolling summaries in append order for prompt-cache stability.

        The cache contract is append-only: keep the same prefix and append new
        suffix blocks.  Do not use a "latest N" sliding window, because dropping
        the oldest visible block changes the request prefix and destroys provider
        prompt-cache hits.  Only when the ledger is close to the prompt budget do
        we roll the oldest prefix into one stable synthetic summary, then append
        newer blocks after it.

        ``limit`` is retained for API compatibility, but it is no longer a
        sliding-window cutoff.  ``max_chars`` is the explosion guard.
        """
        _ = limit
        budget = max(SUMMARY_LEDGER_MIN_BUDGET_CHARS, int(max_chars))
        rows = self._active_summary_rows(session_id, scope)
        if self._summary_blocks_chars(rows) > budget:
            self._roll_up_summary_prefix(session_id, scope, rows, budget=budget, now_ms=now_ms)
            rows = self._active_summary_rows(session_id, scope)
        return [self._summary_block(row) for row in rows]

    def _active_summary_rows(self, session_id: str, scope: str) -> list:
        return self.db.query_all(
            """SELECT id, from_seq, to_seq, summary, source_hash, model_name, prompt_version, created_at_ms
            FROM semantic_summaries
            WHERE session_id=? AND scope=? AND status='active'
            ORDER BY from_seq ASC, to_seq ASC, created_at_ms ASC""",
            (session_id, scope),
        )

    def _summary_block(self, row) -> str:
        return f"SUMMARY_BLOCK seq={int(row['from_seq'])}-{int(row['to_seq'])}\n{str(row['summary'])[:SUMMARY_BLOCK_MAX_CHARS]}"

    def _summary_blocks_chars(self, rows: list) -> int:
        if not rows:
            return 0
        return sum(len(self._summary_block(row)) + 2 for row in rows)

    def _roll_up_summary_prefix(self, session_id: str, scope: str, rows: list, *, budget: int, now_ms: int | None = None) -> None:
        if len(rows) <= 1:
            return

        prefix = self._rollup_prefix_rows(rows, budget=budget)
        if not prefix:
            return

        from_seq = int(prefix[0]["from_seq"])
        to_seq = int(prefix[-1]["to_seq"])
        rollup = self._rollup_summary_text(prefix, max_chars=self._rollup_anchor_chars(budget))
        source_hash = semantic_hash("semantic_summary_rollup", session_id, scope, from_seq, to_seq, [row["id"] for row in prefix], rollup)
        existing = self.db.query_one(
            "SELECT id FROM semantic_summaries WHERE session_id=? AND scope=? AND source_hash=? AND status='active'",
            (session_id, scope, source_hash),
        )
        if existing is not None:
            return

        now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        summary_id = new_id("semsum")
        ids = [row["id"] for row in prefix]
        placeholders = ",".join("?" for _ in ids)
        with self.db.transaction():
            self.db.execute(
                f"UPDATE semantic_summaries SET status=? WHERE id IN ({placeholders})",
                (SUMMARY_ROLLUP_STATUS, *ids),
            )
            self.db.execute(
                """INSERT INTO semantic_summaries
                (id,session_id,scope,from_seq,to_seq,summary,source_hash,model_name,prompt_version,created_at_ms,status)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    summary_id,
                    session_id,
                    scope,
                    from_seq,
                    to_seq,
                    rollup,
                    source_hash,
                    None,
                    SUMMARY_ROLLUP_PROMPT_VERSION,
                    now_ms,
                    "active",
                ),
            )

    def _rollup_prefix_rows(self, rows: list, *, budget: int) -> list:
        """Choose the oldest rows to fold while preserving a recent suffix."""
        if len(rows) <= 1:
            return []

        # Keep a suffix intact and move only the oldest prefix forward into one
        # synthetic anchor.  Leave room for both the anchor and future dynamic
        # events; otherwise a single new block would immediately force another
        # roll-up.
        suffix_budget = max(SUMMARY_LEDGER_MIN_BUDGET_CHARS, int(budget * SUMMARY_ROLLUP_SUFFIX_BUDGET_RATIO))
        suffix_chars = 0
        suffix_len = 0
        for row in reversed(rows):
            block_chars = len(self._summary_block(row)) + 2
            if suffix_len > 0 and suffix_chars + block_chars > suffix_budget:
                break
            suffix_chars += block_chars
            suffix_len += 1

        if suffix_len >= len(rows):
            suffix_len = 1
        return rows[: len(rows) - suffix_len]

    def _rollup_anchor_chars(self, budget: int) -> int:
        return max(
            SUMMARY_LEDGER_MIN_BUDGET_CHARS,
            min(SUMMARY_ROLLUP_ANCHOR_MAX_CHARS, int(budget * SUMMARY_ROLLUP_ANCHOR_BUDGET_RATIO)),
        )

    def _rollup_summary_text(self, rows: list, *, max_chars: int) -> str:
        lines = [
            SUMMARY_ROLLUP_HEADER,
            f"range: seq={int(rows[0]['from_seq'])}-{int(rows[-1]['to_seq'])}",
            "The older immutable summary ledger was folded only after reaching the context budget. Newer suffix blocks remain appended after this anchor.",
        ]
        for row in rows:
            summary = " ".join(str(row["summary"]).split())
            lines.append(f"- seq={int(row['from_seq'])}-{int(row['to_seq'])}: {summary[:500]}")
            text = "\n".join(lines)
            if len(text) >= max_chars:
                return text[:max_chars]
        return "\n".join(lines)[:max_chars]

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
