from __future__ import annotations

from advanced_agent.models import Authority, AgentRole, InteractionState, MainVisibleState, Message, StreamDelta, new_id
from advanced_agent.stores.sqlite_store import SQLiteStore


class SessionStore:
    def __init__(self, db: SQLiteStore) -> None:
        self.db = db

    def create_session(self, title: str, now_ms: int, session_id: str | None = None) -> str:
        sid = session_id or new_id("sess")
        self.db.execute(
            "INSERT INTO sessions(id,title,status,created_at_ms,updated_at_ms) VALUES(?,?,?,?,?)",
            (sid, title, "active", now_ms, now_ms),
        )
        return sid

    def get_or_create_default_session(self, title: str, now_ms: int) -> str:
        row = self.db.query_one(
            "SELECT id FROM sessions WHERE title=? AND status='active' ORDER BY updated_at_ms DESC LIMIT 1",
            (title,),
        )
        if row is not None:
            self.db.execute("UPDATE sessions SET updated_at_ms=? WHERE id=?", (now_ms, row["id"]))
            return row["id"]
        row = self.db.query_one("SELECT id FROM sessions WHERE status='active' ORDER BY updated_at_ms DESC, created_at_ms DESC LIMIT 1")
        if row is not None:
            self.db.execute("UPDATE sessions SET title=?, updated_at_ms=? WHERE id=?", (title, now_ms, row["id"]))
            return row["id"]
        return self.create_session(title=title, now_ms=now_ms)

    def append_message(self, message: Message) -> None:
        self.db.execute(
            "INSERT INTO messages(id,session_id,request_id,role,content,seq,created_at_ms) VALUES(?,?,?,?,?,?,?)",
            (message.id, message.session_id, message.request_id, message.role, message.content, message.seq, message.created_at_ms),
        )

    def latest_message(self, session_id: str, role: str | None = None) -> Message | None:
        if role is None:
            row = self.db.query_one("SELECT * FROM messages WHERE session_id=? ORDER BY created_at_ms DESC LIMIT 1", (session_id,))
        else:
            row = self.db.query_one("SELECT * FROM messages WHERE session_id=? AND role=? ORDER BY created_at_ms DESC LIMIT 1", (session_id, role))
        if row is None:
            return None
        return Message(
            id=row["id"],
            session_id=row["session_id"],
            role=row["role"],
            content=row["content"],
            request_id=row["request_id"],
            seq=row["seq"],
            created_at_ms=row["created_at_ms"],
        )

    def message_for_request(self, session_id: str, request_id: str, role: str = "user") -> Message | None:
        row = self.db.query_one(
            "SELECT * FROM messages WHERE session_id=? AND request_id=? AND role=? ORDER BY created_at_ms DESC LIMIT 1",
            (session_id, request_id, role),
        )
        if row is None:
            return None
        return Message(
            id=row["id"],
            session_id=row["session_id"],
            role=row["role"],
            content=row["content"],
            request_id=row["request_id"],
            seq=row["seq"],
            created_at_ms=row["created_at_ms"],
        )

    def next_stream_seq(self, request_id: str) -> int:
        row = self.db.query_one("SELECT COALESCE(MAX(seq),0)+1 AS next_seq FROM interaction_streams WHERE request_id=?", (request_id,))
        return int(row["next_seq"] if row else 1)

    def append_stream_delta(self, delta: StreamDelta) -> None:
        self.db.execute(
            """INSERT INTO interaction_streams
            (id,session_id,request_id,seq,writer,authority,delta,supersedes_seq,created_at_ms)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                delta.id,
                delta.session_id,
                delta.request_id,
                delta.seq,
                delta.writer.value,
                delta.authority.value,
                delta.text,
                delta.supersedes_seq,
                delta.timestamp_ms,
            ),
        )

    def stream_for_request(self, request_id: str) -> list[StreamDelta]:
        rows = self.db.query_all("SELECT * FROM interaction_streams WHERE request_id=? ORDER BY seq", (request_id,))
        return [
            StreamDelta(
                id=row["id"],
                session_id=row["session_id"],
                request_id=row["request_id"],
                seq=row["seq"],
                writer=AgentRole(row["writer"]),
                authority=Authority(row["authority"]),
                text=row["delta"],
                supersedes_seq=row["supersedes_seq"],
                timestamp_ms=row["created_at_ms"],
            )
            for row in rows
        ]

    def set_main_visible_state(self, state: MainVisibleState) -> None:
        self.db.execute(
            "DELETE FROM main_visible_state WHERE session_id=? AND request_id=?",
            (state.session_id, state.request_id),
        )
        self.db.execute(
            "INSERT INTO main_visible_state(id,session_id,request_id,status,visible_summary,updated_at_ms) VALUES(?,?,?,?,?,?)",
            (state.id, state.session_id, state.request_id, state.status, state.visible_summary, state.updated_at_ms),
        )

    def get_main_visible_state(self, session_id: str, request_id: str) -> MainVisibleState | None:
        row = self.db.query_one("SELECT * FROM main_visible_state WHERE session_id=? AND request_id=?", (session_id, request_id))
        if row is None:
            return None
        return MainVisibleState(
            id=row["id"],
            session_id=row["session_id"],
            request_id=row["request_id"],
            status=row["status"],
            visible_summary=row["visible_summary"],
            updated_at_ms=row["updated_at_ms"],
        )

    def set_interaction_state(self, state: InteractionState) -> None:
        self.db.execute("DELETE FROM interaction_state WHERE session_id=? AND request_id=?", (state.session_id, state.request_id))
        self.db.execute(
            "INSERT INTO interaction_state(id,session_id,request_id,status,last_sent_seq,updated_at_ms) VALUES(?,?,?,?,?,?)",
            (state.id, state.session_id, state.request_id, state.status, state.last_sent_seq, state.updated_at_ms),
        )

    def session_messages(self, session_id: str, include_compacted: bool = False, limit: int | None = None) -> list[Message]:
        where = "session_id=?" if include_compacted else "session_id=? AND compacted=0"
        sql = f"SELECT * FROM messages WHERE {where} ORDER BY created_at_ms"
        params: tuple = (session_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (session_id, limit)
        rows = self.db.query_all(sql, params)
        return [
            Message(
                id=row["id"],
                session_id=row["session_id"],
                role=row["role"],
                content=row["content"],
                request_id=row["request_id"],
                seq=row["seq"],
                created_at_ms=row["created_at_ms"],
            )
            for row in rows
        ]

    def session_context_lines(self, session_id: str, include_compacted: bool = False, limit: int | None = None) -> list[str]:
        """Return user-visible dialogue lines for prompt context.

        Messages store user input. Interaction streams store assistant-visible
        outputs. For prompt continuity, main needs both; otherwise it may claim
        it cannot see earlier replies even though they are in SQLite.
        """
        message_where = "session_id=?" if include_compacted else "session_id=? AND compacted=0"
        params: tuple = (session_id, session_id)
        sql = f"""
        SELECT created_at_ms, 'user' AS role, content AS text FROM messages WHERE {message_where}
        UNION ALL
        SELECT created_at_ms, 'assistant' AS role, delta AS text FROM interaction_streams
        WHERE session_id=? AND authority='authoritative'
        {'' if include_compacted else "AND request_id IN (SELECT request_id FROM messages WHERE session_id=? AND compacted=0)"}
        ORDER BY created_at_ms
        """
        if limit is not None:
            sql += " LIMIT ?"
            params = (session_id, session_id, limit) if include_compacted else (session_id, session_id, session_id, limit)
        elif not include_compacted:
            params = (session_id, session_id, session_id)
        rows = self.db.query_all(sql, params)
        return [f"{row['role']}: {row['text']}" for row in rows]

    def uncompacted_char_count(self, session_id: str) -> int:
        row = self.db.query_one("SELECT COALESCE(SUM(LENGTH(content)),0) AS total FROM messages WHERE session_id=? AND compacted=0", (session_id,))
        return int(row["total"] if row else 0)

    def mark_compacted_before(self, session_id: str, before_message_id: str) -> int:
        pivot = self.db.query_one("SELECT created_at_ms FROM messages WHERE id=?", (before_message_id,))
        if pivot is None:
            return 0
        before_ms = pivot["created_at_ms"]
        rows = self.db.query_all("SELECT id FROM messages WHERE session_id=? AND compacted=0 AND created_at_ms<=?", (session_id, before_ms))
        self.db.execute("UPDATE messages SET compacted=1 WHERE session_id=? AND compacted=0 AND created_at_ms<=?", (session_id, before_ms))
        return len(rows)

    def clear_context_before_ms(self, session_id: str, cutoff_ms: int) -> int:
        rows = self.db.query_all("SELECT id FROM messages WHERE session_id=? AND compacted=0 AND created_at_ms<=?", (session_id, cutoff_ms))
        self.db.execute("UPDATE messages SET compacted=1 WHERE session_id=? AND compacted=0 AND created_at_ms<=?", (session_id, cutoff_ms))
        self.db.execute("UPDATE sessions SET updated_at_ms=? WHERE id=?", (cutoff_ms, session_id))
        return len(rows)

    def rollback_context_to_ms(self, session_id: str, cutoff_ms: int) -> int:
        """Hide messages after cutoff from active prompt context.

        This is a context rollback, not history deletion. Raw messages and
        streams remain auditable; normal context builders ignore compacted rows.
        """
        rows = self.db.query_all("SELECT id FROM messages WHERE session_id=? AND compacted=0 AND created_at_ms>?", (session_id, cutoff_ms))
        self.db.execute("UPDATE messages SET compacted=1 WHERE session_id=? AND compacted=0 AND created_at_ms>?", (session_id, cutoff_ms))
        self.db.execute("UPDATE sessions SET updated_at_ms=? WHERE id=?", (cutoff_ms, session_id))
        return len(rows)

    def prune_compacted_before_ms(self, session_id: str, cutoff_ms: int, limit: int = 500) -> int:
        """Physically delete old compacted raw rows after durable summaries exist."""

        message_rows = self.db.query_all(
            "SELECT id, request_id FROM messages WHERE session_id=? AND compacted=1 AND pinned=0 AND created_at_ms<? ORDER BY created_at_ms LIMIT ?",
            (session_id, cutoff_ms, limit),
        )
        if not message_rows:
            return 0
        message_ids = [row["id"] for row in message_rows]
        request_ids = [row["request_id"] for row in message_rows if row["request_id"]]
        with self.db.transaction():
            if request_ids:
                placeholders = ",".join("?" for _ in request_ids)
                self.db.execute(
                    f"DELETE FROM interaction_streams WHERE session_id=? AND request_id IN ({placeholders})",
                    (session_id, *request_ids),
                )
            placeholders = ",".join("?" for _ in message_ids)
            self.db.execute(f"DELETE FROM messages WHERE id IN ({placeholders})", tuple(message_ids))
        return len(message_ids)


    def raw_tail_lines(self, session_id: str, limit: int = 80, max_chars: int = 800, include_compacted: bool = True) -> list[str]:
        """Return a bounded ring-buffer-like tail of raw dialogue rows.

        This is intentionally not semantic memory. It lets the model pull a
        small recent raw window on demand without overflowing the main prompt.
        """
        message_where = "session_id=?" if include_compacted else "session_id=? AND compacted=0"
        params: tuple = (session_id, session_id, limit)
        sql = f"""
        SELECT created_at_ms, 'message' AS source, role, content AS text, request_id, seq
        FROM messages WHERE {message_where}
        UNION ALL
        SELECT created_at_ms, 'stream' AS source, writer || ':' || authority AS role, delta AS text, request_id, seq
        FROM interaction_streams WHERE session_id=? AND LENGTH(delta)>0
        ORDER BY created_at_ms DESC, source DESC, seq DESC
        LIMIT ?
        """
        rows = list(reversed(self.db.query_all(sql, params)))
        return [
            f"{row['created_at_ms']} {row['source']}/{row['role']} req={row['request_id'] or '-'}: {row['text'][:max_chars]}"
            for row in rows
        ]

    def context_stats(self, session_id: str) -> dict:
        row = self.db.query_one(
            """SELECT
            COUNT(*) AS total_messages,
            COALESCE(SUM(CASE WHEN compacted=0 THEN 1 ELSE 0 END),0) AS active_messages,
            COALESCE(SUM(CASE WHEN compacted=1 THEN 1 ELSE 0 END),0) AS compacted_messages,
            COALESCE(SUM(CASE WHEN compacted=0 THEN LENGTH(content) ELSE 0 END),0) AS active_chars,
            MIN(created_at_ms) AS first_message_at_ms,
            MAX(created_at_ms) AS last_message_at_ms
            FROM messages WHERE session_id=?""",
            (session_id,),
        )
        return dict(row) if row is not None else {}
