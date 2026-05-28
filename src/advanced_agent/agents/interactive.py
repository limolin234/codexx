from __future__ import annotations

import re

from advanced_agent.models import AgentRole, Authority, InteractionState, Message, StreamDelta
from advanced_agent.stores.session_store import SessionStore
from advanced_agent.time_service import TimeService
from advanced_agent.llm import ChatMessage, OpenAICompatibleClient, LLMError
from advanced_agent.prompt_builder import PromptBuilder


class InteractiveAgent:
    """Fast provisional feedback layer.

    This agent is deliberately shallow. It acknowledges input, records stream
    state, and leaves semantic authority to MainAgent.
    """

    def __init__(self, sessions: SessionStore, time: TimeService, model: OpenAICompatibleClient | None = None, prompt_builder: PromptBuilder | None = None) -> None:
        self.sessions = sessions
        self.time = time
        self.model = model
        self.prompt_builder = prompt_builder

    def receive_user_message(self, session_id: str, request_id: str, text: str) -> StreamDelta:
        now = self.time.wall_ms()
        self.sessions.append_message(
            Message(session_id=session_id, request_id=request_id, role="user", content=text, created_at_ms=now)
        )
        seq = self.sessions.next_stream_seq(request_id)
        reply = self._quick_reply(text)
        delta = StreamDelta(
            session_id=session_id,
            request_id=request_id,
            seq=seq,
            writer=AgentRole.INTERACTIVE,
            authority=Authority.PROVISIONAL,
            text=reply,
            timestamp_ms=now,
        )
        self.sessions.append_stream_delta(delta)
        self.sessions.set_interaction_state(
            InteractionState(session_id=session_id, request_id=request_id, status="provisional_replied", last_sent_seq=seq, updated_at_ms=now)
        )
        return delta


    def _quick_reply(self, text: str) -> str:
        if self.model is None:
            return ""
        try:
            bundle = self.prompt_builder.interactive_quick(text) if self.prompt_builder else None
            messages = bundle.messages if bundle else [ChatMessage(role="system", content="你是快速交互层，只做一句临时反馈。"), ChatMessage(role="user", content=text)]
            return self._normalize_silence(self.model.chat(messages).strip())
        except LLMError as exc:
            return ""

    def _deterministic_quick_reply(self, text: str) -> str | None:
        lowered = text.lower()
        if any(key in text for key in ("记录", "上下文", "之前", "刚才")):
            return "我查一下记录。"
        if any(key in text for key in ("项目在哪", "项目在哪里", "目录", "路径", "文件系统")) or any(key in lowered for key in ("cwd", "project root", "where is project")):
            return "我查一下运行目录。"
        if any(key in text for key in ("任务状态", "任务进度", "任务ID", "任务 id", "输出", "hook")) or any(key in lowered for key in ("task", "tail", "status", "hook")):
            return "我查一下任务状态。"
        if any(key in text for key in ("有什么工具", "能用什么工具", "可用工具", "工具列表", "能力列表")) or "tool" in lowered:
            return "我查一下可用能力。"
        return None


    def render_main_reply(self, session_id: str, request_id: str, main_text: str) -> StreamDelta:
        """Render authoritative main-agent content in the interactive voice.

        The user-facing channel should stay consistent: users talk to the
        interactive layer, while main remains the internal semantic authority.
        """
        now = self.time.wall_ms()
        seq = self.sessions.next_stream_seq(request_id)
        rendered = self._render_authoritative(main_text)
        delta = StreamDelta(
            session_id=session_id,
            request_id=request_id,
            seq=seq,
            writer=AgentRole.INTERACTIVE,
            authority=Authority.AUTHORITATIVE,
            text=rendered,
            timestamp_ms=now,
            supersedes_seq=seq - 1 if seq > 1 else None,
        )
        self.sessions.append_stream_delta(delta)
        self.sessions.set_interaction_state(
            InteractionState(session_id=session_id, request_id=request_id, status="authoritative_rendered", last_sent_seq=seq, updated_at_ms=now)
        )
        return delta

    def _render_authoritative(self, main_text: str) -> str:
        if self._normalize_silence(main_text) == "":
            return ""
        if self.model is None:
            return self._sanitize_internal_terms(main_text)
        try:
            bundle = self.prompt_builder.interactive_render(main_text) if self.prompt_builder else None
            messages = bundle.messages if bundle else [ChatMessage(role="system", content="把内部结论简洁复述给用户。"), ChatMessage(role="user", content=main_text)]
            return self._normalize_silence(self.model.chat(messages).strip())
        except LLMError:
            return self._sanitize_internal_terms(main_text)

    def _normalize_silence(self, text: str) -> str:
        normalized = text.strip().lower()
        if normalized in {"<silent>", "silent", "[silent]", "（silent）", "沉默", "不回复"}:
            return ""
        return text

    def _sanitize_internal_terms(self, text: str) -> str:
        replacements = {
            "main agent": "我",
            "Main agent": "我",
            "主 agent": "我",
            "interactive agent": "交互层",
            "Interactive agent": "交互层",
            "interactive": "快速响应部分",
            "Interactive": "快速响应部分",
            "audit agent": "审核层",
            "supervisor": "运行时",
        }
        sanitized = text
        for src, dst in replacements.items():
            sanitized = sanitized.replace(src, dst)
        sanitized = re.sub(r"\btask_[0-9a-fA-F]{8,}\b", "刚才那个后台任务", sanitized)
        sanitized = re.sub(r"\breq_[0-9a-fA-F]{8,}\b", "这次请求", sanitized)
        return sanitized
