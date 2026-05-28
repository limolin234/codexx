from __future__ import annotations

from dataclasses import dataclass

from advanced_agent.capabilities import BackendRegistry
from advanced_agent.context_builder import ContextBuilder
from advanced_agent.llm import ChatMessage
from advanced_agent.stores.profile_store import PromptOverlayStore


@dataclass(slots=True)
class PromptBundle:
    messages: list[ChatMessage]
    scope: str
    purpose: str


class PromptBuilder:
    """Central prompt assembly path for model-backed agents."""

    def __init__(self, context_builder: ContextBuilder, overlays: PromptOverlayStore, default_scope: str = "project:advanced_agent", capabilities: BackendRegistry | None = None) -> None:
        self.context_builder = context_builder
        self.overlays = overlays
        self.default_scope = default_scope
        self.capabilities = capabilities

    def interactive_quick(self, user_text: str, scope: str | None = None) -> PromptBundle:
        scope = scope or self.default_scope
        overlays = self.overlays.overlays_for(scope, "interactive", max_total_chars=1000)
        capability_text = self.capabilities.list_for_prompt(max_items=12) if self.capabilities else "(runtime capabilities unavailable)"
        system = "\n".join([
            "你是 Advanced Agent 的用户交互声音。用户应该感觉是在和一个统一的 AI 交流。",
            "背后的深度思考、大小模型、工具调用、任务执行都不要暴露成多个 agent 或多个模型。",
            "你的风格由深度思考层管理：认真、直接、有一点个性，但不要瞎编事实。",
            "不要自己做复杂语义判断；不要声称已经执行工具；不要编造能力边界、部署环境或文件系统状态。",
            "可以说：我看一下、我先确认一下、我试试。不要说“主 agent”。",
            "如果立即回复只会制造噪音，或者更适合等结果回来再说，可以只输出 <silent>。",
            "如果用户问记录、上下文、之前在做什么，只说“我查一下记录/我看一下上下文”，不要说自己没有权限或职责有限。",
            "如果用户问你有什么工具/能力，只能根据下面 Runtime capabilities 概括，不要引用 ChatGPT/宿主调试环境的工具。",
            "Runtime capabilities:",
            capability_text,
            "风格：认真、直接、有一点个性，不客套，不假装成人。",
            "中文，一句话。",
            *overlays,
        ])
        return PromptBundle(
            messages=[ChatMessage(role="system", content=system), ChatMessage(role="user", content=user_text)],
            scope=scope,
            purpose="interactive_quick",
        )

    def interactive_render(self, main_text: str, scope: str | None = None) -> PromptBundle:
        scope = scope or self.default_scope
        overlays = self.overlays.overlays_for(scope, "interactive", max_total_chars=1000)
        system = "\n".join([
            "你是 Advanced Agent 的用户交互声音。请把内部结论复述给用户。",
            "你是深度思考结果的嘴替和表达层；用户应该感知为同一个 AI 在说话。",
            "保持口吻一致、简洁、准确，有一点个性，但不要自作主张改语义。",
            "不要增加新承诺，不要改变内部结论的语义。",
            "用户应该感觉是在和一个统一的 AI 交流；不要提 main agent、interactive agent、大小模型或内部 agent 分工。",
            "不要主动展示 request_id 等调试编号。",
            "不要展示 task_id；如果需要引用任务，就说“刚才那个后台任务/最近的检查任务”。模型和运行时内部能查，用户不需要记编号。",
            "如果内部结论没有必要对用户说，或者只是后台状态无变化，可以只输出 <silent>。",
            "中文。",
            *overlays,
        ])
        return PromptBundle(
            messages=[ChatMessage(role="system", content=system), ChatMessage(role="user", content=main_text)],
            scope=scope,
            purpose="interactive_render",
        )

    def main_decision(self, session_id: str, request_id: str, user_text: str, scope: str | None = None) -> PromptBundle:
        scope = scope or self.default_scope
        overlays = self.overlays.overlays_for(scope, "main", max_total_chars=1500)
        built = self.context_builder.build_for_main(session_id, user_text, scope=scope)
        recent = "\n".join(built.recent_messages)
        memories = "\n".join(_memory_line(hit) for hit in built.retrieved_memories)
        capability_text = self.capabilities.list_for_prompt() if self.capabilities else "(capabilities unavailable)"
        system = "\n".join([
            "你是 Advanced Agent 的 main agent，是语义权威。",
            "用户不直接与你交流；你的结论会由 interactive agent 复述。",
            "请给出简洁、可靠的内部结论，不要编造已执行的动作。",
            "如果需要任务执行，只表达任务意图，不要直接声称已经完成。",
            "如果用户问项目位置/当前目录，优先使用 project_info，不要启动后台任务。",
            "如果用户问任务状态但没有 task_id，优先使用 task_list 找最近任务，再查 task_state/task_tail。",
            "Recent context 是当前可见记录；只要其中有内容，就不要声称完全没有上下文或记录。",
            "Retrieved memory 来自统一相量数据库，是可信的长期项目记忆；每条记忆可能按 project/time/methodology/feature/decision/preference/chat 等 facet 被召回。",
            "如果需要更多原始最近消息，不要要求用户重述；应调用 session.raw_tail/session_raw_tail 拉取 bounded raw tail。",
            "如果 Recent context 与 Retrieved memory 冲突，优先相信时间更新、来源更具体的内容，并简短说明不确定性。",
            "如果记录不足，说明“基于当前可见记录只能判断...”，并主动给出下一步检查方式。",
            "Available abstract capabilities:",
            capability_text,
            *overlays,
        ])
        user = "\n".join([
            f"request_id: {request_id}",
            "Recent context:",
            recent or "(none)",
            "Retrieved memory:",
            memories or "(none)",
            "Latest user message:",
            user_text,
        ])
        return PromptBundle(
            messages=[ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)],
            scope=scope,
            purpose="main_decision",
        )


def _memory_line(hit) -> str:
    label_kind = getattr(hit, "label_kind", None) or "memory"
    content = getattr(hit, "content", None)
    detail = (content or hit.summary or "")[:800]
    if detail and detail != hit.summary:
        return f"- [{hit.type}/{label_kind}] {hit.summary}\n  content: {detail}"
    return f"- [{hit.type}/{label_kind}] {hit.summary}"
