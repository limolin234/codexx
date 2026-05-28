from __future__ import annotations

from advanced_agent.models import new_id
from advanced_agent.stores.sqlite_store import SQLiteStore


class ProfileStore:
    def __init__(self, db: SQLiteStore) -> None:
        self.db = db

    def upsert_profile(self, scope: str, summary: str, now_ms: int, confidence: float = 0.8, max_chars: int = 1200) -> str:
        existing = self.db.query_one("SELECT id FROM user_profiles WHERE scope=?", (scope,))
        if existing:
            profile_id = existing["id"]
            self.db.execute(
                "UPDATE user_profiles SET summary=?, updated_at_ms=?, confidence=?, max_chars=? WHERE id=?",
                (summary[:max_chars], now_ms, confidence, max_chars, profile_id),
            )
            return profile_id
        profile_id = new_id("profile")
        self.db.execute(
            "INSERT INTO user_profiles(id,scope,summary,updated_at_ms,confidence,max_chars) VALUES(?,?,?,?,?,?)",
            (profile_id, scope, summary[:max_chars], now_ms, confidence, max_chars),
        )
        return profile_id

    def get_profile(self, scope: str) -> str | None:
        row = self.db.query_one("SELECT summary FROM user_profiles WHERE scope=?", (scope,))
        return None if row is None else row["summary"]


class PromptOverlayStore:
    def __init__(self, db: SQLiteStore) -> None:
        self.db = db

    def replace_overlay(self, scope: str, target_agent: str, category: str, content: str, now_ms: int, priority: int = 0, max_chars: int = 600, source: str | None = None) -> str:
        self.db.execute(
            "DELETE FROM prompt_overlays WHERE scope=? AND target_agent=? AND category=?",
            (scope, target_agent, category),
        )
        overlay_id = new_id("overlay")
        self.db.execute(
            """INSERT INTO prompt_overlays
            (id,scope,target_agent,category,content,priority,status,source,updated_at_ms,max_chars)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (overlay_id, scope, target_agent, category, content[:max_chars], priority, "active", source, now_ms, max_chars),
        )
        return overlay_id

    def overlays_for(self, scope: str, target_agent: str, max_total_chars: int = 1500) -> list[str]:
        rows = self.db.query_all(
            """SELECT content FROM prompt_overlays WHERE scope=? AND target_agent=? AND status='active'
            ORDER BY priority DESC, updated_at_ms DESC""",
            (scope, target_agent),
        )
        result: list[str] = []
        total = 0
        for row in rows:
            text = row["content"]
            if total + len(text) > max_total_chars:
                remaining = max_total_chars - total
                if remaining <= 0:
                    break
                text = text[:remaining]
            result.append(text)
            total += len(text)
        return result
