from __future__ import annotations

from dataclasses import dataclass

from advanced_agent.stores.profile_store import ProfileStore, PromptOverlayStore
from advanced_agent.stores.session_store import SessionStore
from advanced_agent.time_service import TimeService


@dataclass(slots=True)
class PreferenceLimits:
    total_profile_chars: int = 1200
    category_chars: int = 280
    overlay_chars: int = 600


class PreferenceWorker:
    """Maintain user profile and prompt overlays from interaction history.

    First version is deterministic and bounded. Later this can be backed by a
    small preference-maintenance model.
    """

    categories = {
        "architecture": ("架构", "模块", "解耦", "可维护", "屎山", "contract"),
        "interaction": ("interactive", "交互", "main agent", "复述", "快速反馈", "流式"),
        "safety": ("审核", "安全", "危险", "stop", "kill", "打断"),
        "memory": ("记忆", "画像", "喜好", "相量", "向量", "prompt"),
    }

    def __init__(self, sessions: SessionStore, profiles: ProfileStore, overlays: PromptOverlayStore, time: TimeService, limits: PreferenceLimits | None = None) -> None:
        self.sessions = sessions
        self.profiles = profiles
        self.overlays = overlays
        self.time = time
        self.limits = limits or PreferenceLimits()

    def update_from_session(self, session_id: str, scope: str = "project:advanced_agent") -> str:
        rows = self.sessions.db.query_all(
            "SELECT content FROM messages WHERE session_id=? AND role='user' ORDER BY created_at_ms DESC LIMIT 80",
            (session_id,),
        )
        texts = [row["content"] for row in reversed(rows)]
        categorized = {name: [] for name in self.categories}
        for text in texts:
            lower = text.lower()
            for name, keys in self.categories.items():
                if any(key.lower() in lower for key in keys):
                    categorized[name].append(text)

        lines: list[str] = []
        for name, items in categorized.items():
            if not items:
                continue
            joined = "；".join(items[-3:])
            lines.append(f"[{name}] {joined[: self.limits.category_chars]}")
        if not lines:
            lines.append("[general] 暂无稳定偏好，仅保留当前会话上下文。")
        summary = "\n".join(lines)[: self.limits.total_profile_chars]
        now = self.time.wall_ms()
        profile_id = self.profiles.upsert_profile(scope, summary, now, max_chars=self.limits.total_profile_chars)

        main_overlay = self._overlay_for_main(summary)
        interactive_overlay = self._overlay_for_interactive(summary)
        self.overlays.replace_overlay(scope, "main", "user_profile", main_overlay, now, priority=50, max_chars=self.limits.overlay_chars, source=profile_id)
        self.overlays.replace_overlay(scope, "interactive", "user_profile", interactive_overlay, now, priority=50, max_chars=self.limits.overlay_chars, source=profile_id)
        return profile_id

    def _overlay_for_main(self, summary: str) -> str:
        return (
            "User/profile constraints: prioritize maintainable architecture, clear module boundaries, "
            "and avoid rushing demos when architecture is unsettled. Current bounded profile:\n" + summary
        )[: self.limits.overlay_chars]

    def _overlay_for_interactive(self, summary: str) -> str:
        return (
            "Interactive style constraints: respond quickly, do not make final semantic decisions, "
            "and render main-agent decisions consistently. Current bounded profile:\n" + summary
        )[: self.limits.overlay_chars]
