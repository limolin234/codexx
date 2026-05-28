from __future__ import annotations

from advanced_agent.models import TaskSpec, TaskState, new_id
from advanced_agent.stores.sqlite_store import SQLiteStore, dumps, loads


class TaskStore:
    def __init__(self, db: SQLiteStore) -> None:
        self.db = db

    def create_task(self, spec: TaskSpec, now_ms: int) -> str:
        self.db.execute(
            """INSERT INTO tasks
            (id,session_id,backend,goal,workdir,status,priority,created_at_ms,updated_at_ms)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (spec.id, spec.session_id, spec.backend, spec.goal, spec.workdir, "created", spec.priority, now_ms, now_ms),
        )
        self.db.execute(
            """INSERT INTO task_state
            (task_id,status,stage,elapsed_ms,idle_ms,latest_summary,need_attention,can_stop,can_kill,updated_at_ms)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (spec.id, "created", None, 0, 0, None, 0, 1, 0, now_ms),
        )
        return spec.id

    def get_task_spec(self, task_id: str) -> TaskSpec | None:
        row = self.db.query_one("SELECT id,session_id,backend,goal,workdir,priority FROM tasks WHERE id=?", (task_id,))
        if row is None:
            return None
        return TaskSpec(
            id=row["id"],
            session_id=row["session_id"],
            backend=row["backend"],
            goal=row["goal"],
            workdir=row["workdir"],
            priority=row["priority"],
        )

    def update_task_state(self, task_id: str, status: str, now_ms: int, stage: str | None = None, summary: str | None = None) -> None:
        self.db.execute(
            "UPDATE tasks SET status=?, stage=COALESCE(?,stage), updated_at_ms=? WHERE id=?",
            (status, stage, now_ms, task_id),
        )
        self.db.execute(
            """UPDATE task_state SET status=?, stage=COALESCE(?,stage), latest_summary=COALESCE(?,latest_summary),
            updated_at_ms=? WHERE task_id=?""",
            (status, stage, summary, now_ms, task_id),
        )

    def append_event(self, task_id: str, type_: str, payload: dict, now_ms: int, mono_ms: int) -> str:
        event_id = new_id("taskevt")
        self.db.execute(
            "INSERT INTO task_events(id,task_id,type,payload_json,created_at_ms,mono_ms) VALUES(?,?,?,?,?,?)",
            (event_id, task_id, type_, dumps(payload), now_ms, mono_ms),
        )
        return event_id

    def append_output(self, task_id: str, stream: str, text: str, now_ms: int, max_chunk_chars: int = 8192) -> str:
        if len(text) > max_chunk_chars:
            text = text[:max_chunk_chars] + "\n...[truncated]\n"
        row = self.db.query_one("SELECT COALESCE(MAX(seq),0)+1 AS next_seq FROM task_output_chunks WHERE task_id=? AND stream=?", (task_id, stream))
        seq = int(row["next_seq"] if row else 1)
        chunk_id = new_id("chunk")
        self.db.execute(
            "INSERT INTO task_output_chunks(id,task_id,stream,seq,text,created_at_ms) VALUES(?,?,?,?,?,?)",
            (chunk_id, task_id, stream, seq, text, now_ms),
        )
        return chunk_id

    def get_tail(self, task_id: str, limit: int = 100) -> str:
        rows = self.db.query_all(
            """SELECT stream, seq, text FROM task_output_chunks WHERE task_id=?
            ORDER BY created_at_ms DESC, seq DESC LIMIT ?""",
            (task_id, limit),
        )
        rows = list(reversed(rows))
        return "\n".join(f"[{row['stream']}:{row['seq']}] {row['text']}" for row in rows)

    def get_state(self, task_id: str) -> TaskState | None:
        row = self.db.query_one("SELECT * FROM task_state WHERE task_id=?", (task_id,))
        if row is None:
            return None
        return TaskState(
            task_id=row["task_id"],
            status=row["status"],
            stage=row["stage"],
            latest_summary=row["latest_summary"],
            need_attention=bool(row["need_attention"]),
            can_stop=bool(row["can_stop"]),
            updated_at_ms=row["updated_at_ms"],
        )

    def list_tasks(self, statuses: list[str] | None = None, limit: int = 50) -> list[dict]:
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            rows = self.db.query_all(
                f"SELECT id,session_id,backend,goal,workdir,status,stage,priority,created_at_ms,updated_at_ms FROM tasks WHERE status IN ({placeholders}) ORDER BY updated_at_ms DESC LIMIT ?",
                (*statuses, limit),
            )
        else:
            rows = self.db.query_all(
                "SELECT id,session_id,backend,goal,workdir,status,stage,priority,created_at_ms,updated_at_ms FROM tasks ORDER BY updated_at_ms DESC LIMIT ?",
                (limit,),
            )
        return [dict(row) for row in rows]

    def append_summary(self, task_id: str, kind: str, summary: str, important_events: list[str], risks: list[str], now_ms: int) -> str:
        summary_id = new_id("summary")
        self.db.execute(
            """INSERT INTO task_summaries(id,task_id,kind,summary,important_events_json,risks_json,created_at_ms)
            VALUES(?,?,?,?,?,?,?)""",
            (summary_id, task_id, kind, summary, dumps(important_events), dumps(risks), now_ms),
        )
        self.db.execute("UPDATE task_state SET latest_summary=?, updated_at_ms=? WHERE task_id=?", (summary, now_ms, task_id))
        return summary_id

    def history(self, task_id: str, output_limit: int = 50, event_limit: int = 50) -> dict:
        state = self.get_state(task_id)
        outputs = self.db.query_all(
            "SELECT stream,seq,text,created_at_ms FROM task_output_chunks WHERE task_id=? ORDER BY created_at_ms DESC, seq DESC LIMIT ?",
            (task_id, output_limit),
        )
        events = self.db.query_all(
            "SELECT type,payload_json,created_at_ms FROM task_events WHERE task_id=? ORDER BY created_at_ms DESC LIMIT ?",
            (task_id, event_limit),
        )
        summaries = self.db.query_all(
            "SELECT kind,summary,important_events_json,risks_json,created_at_ms FROM task_summaries WHERE task_id=? ORDER BY created_at_ms DESC LIMIT 10",
            (task_id,),
        )
        return {
            "state": None if state is None else {
                "task_id": state.task_id,
                "status": state.status,
                "stage": state.stage,
                "latest_summary": state.latest_summary,
                "need_attention": state.need_attention,
                "can_stop": state.can_stop,
                "updated_at_ms": state.updated_at_ms,
            },
            "outputs": [dict(row) for row in reversed(outputs)],
            "events": [
                {"type": row["type"], "payload": loads(row["payload_json"]) or {}, "created_at_ms": row["created_at_ms"]}
                for row in reversed(events)
            ],
            "summaries": [
                {
                    "kind": row["kind"],
                    "summary": row["summary"],
                    "important_events": loads(row["important_events_json"]) or [],
                    "risks": loads(row["risks_json"]) or [],
                    "created_at_ms": row["created_at_ms"],
                }
                for row in reversed(summaries)
            ],
        }
