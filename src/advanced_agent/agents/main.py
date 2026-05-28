from __future__ import annotations

from advanced_agent.capability_executor import CapabilityExecutor, OpenAIToolAdapter
from advanced_agent.models import AgentRole, Authority, MainVisibleState, StreamDelta, TaskSpec
from advanced_agent.stores.main_decision_store import MainDecision, MainDecisionStore
from advanced_agent.stores.session_store import SessionStore
from advanced_agent.supervisor import Supervisor
from advanced_agent.time_service import TimeService
from advanced_agent.llm import ChatMessage, OpenAICompatibleClient, LLMError
from advanced_agent.prompt_builder import PromptBuilder


class MainAgent:
    """Authoritative semantic layer.

    First version is mock/rule-based to validate runtime contracts before model
    integration.
    """

    def __init__(self, sessions: SessionStore, supervisor: Supervisor, time: TimeService, decisions: MainDecisionStore, model: OpenAICompatibleClient | None = None, prompt_builder: PromptBuilder | None = None, capability_executor: CapabilityExecutor | None = None) -> None:
        self.sessions = sessions
        self.supervisor = supervisor
        self.time = time
        self.decisions = decisions
        self.model = model
        self.prompt_builder = prompt_builder
        self.capability_executor = capability_executor

    def handle_request(self, session_id: str, request_id: str, workdir: str) -> StreamDelta:
        reply, tool_records, now = self._prepare_decision(session_id, request_id, workdir)
        return self._record_decision_delta(session_id, request_id, reply, tool_records, now)

    async def handle_request_async(self, session_id: str, request_id: str, workdir: str) -> StreamDelta:
        reply, tool_records, now = await self._prepare_decision_async(session_id, request_id, workdir)
        return self._record_decision_delta(session_id, request_id, reply, tool_records, now)

    def _prepare_decision(self, session_id: str, request_id: str, workdir: str) -> tuple[str, list[dict], int]:
        latest = self.sessions.message_for_request(session_id, request_id, role="user") or self.sessions.latest_message(session_id, role="user")
        text = latest.content if latest else ""
        now = self.time.wall_ms()
        self.sessions.set_main_visible_state(
            MainVisibleState(
                session_id=session_id,
                request_id=request_id,
                status="reasoning_complete",
                visible_summary="main agent 已完成语义判断，并将覆盖 interactive 的临时反馈。",
                updated_at_ms=now,
            )
        )

        tool_records: list[dict] = []

        # In the first version, task spawning is explicit and conservative.
        task_note = ""
        if self.model is None and ("实现" in text or "开始" in text or "codex" in text.lower()):
            task_id = self.supervisor.spawn_task(TaskSpec(session_id=session_id, goal=text, workdir=workdir))
            task_note = f" 已发起后台任务 {task_id}。"
            tool_records.append({"capability": "spawn_task", "task_id": task_id, "source": "rule_fallback"})

        reply, model_tool_records = self._authoritative_reply(session_id, request_id, text)
        tool_records.extend(model_tool_records)
        reply = reply + task_note
        return reply, tool_records, now

    async def _prepare_decision_async(self, session_id: str, request_id: str, workdir: str) -> tuple[str, list[dict], int]:
        latest = self.sessions.message_for_request(session_id, request_id, role="user") or self.sessions.latest_message(session_id, role="user")
        text = latest.content if latest else ""
        now = self.time.wall_ms()
        self.sessions.set_main_visible_state(
            MainVisibleState(
                session_id=session_id,
                request_id=request_id,
                status="reasoning_complete",
                visible_summary="main agent 已完成语义判断，并将覆盖 interactive 的临时反馈。",
                updated_at_ms=now,
            )
        )
        tool_records: list[dict] = []
        task_note = ""
        if self.model is None and ("实现" in text or "开始" in text or "codex" in text.lower()):
            task_id = self.supervisor.spawn_task(TaskSpec(session_id=session_id, goal=text, workdir=workdir))
            task_note = f" 已发起后台任务 {task_id}。"
            tool_records.append({"capability": "spawn_task", "task_id": task_id, "source": "rule_fallback"})
        reply, model_tool_records = await self._authoritative_reply_async(session_id, request_id, text)
        tool_records.extend(model_tool_records)
        return reply + task_note, tool_records, now

    def _record_decision_delta(self, session_id: str, request_id: str, reply: str, tool_records: list[dict], now: int) -> StreamDelta:
        latest = self.sessions.message_for_request(session_id, request_id, role="user") or self.sessions.latest_message(session_id, role="user")
        self.decisions.add(
            MainDecision(
                session_id=session_id,
                request_id=request_id,
                intent=(latest.content if latest else "")[:500],
                decision_type="authoritative_reply",
                internal_summary=reply[:1200],
                user_visible_instruction=reply,
                task_requests=tool_records,
                audit_status="handled_by_runtime",
                created_at_ms=now,
            )
        )
        supersedes_seq = self.sessions.next_stream_seq(request_id) - 1
        seq = supersedes_seq + 1
        delta = StreamDelta(
            session_id=session_id,
            request_id=request_id,
            seq=seq,
            writer=AgentRole.MAIN,
            authority=Authority.AUTHORITATIVE,
            supersedes_seq=supersedes_seq if supersedes_seq > 0 else None,
            text=reply,
            timestamp_ms=now,
        )
        # Main output is internal semantic authority. The user-facing stream is
        # rendered by InteractiveAgent.render_main_reply().
        return delta


    def _authoritative_reply(self, session_id: str, request_id: str, text: str) -> tuple[str, list[dict]]:
        if self.model is None:
            return self._rule_reply(session_id, text), []
        try:
            bundle = self.prompt_builder.main_decision(session_id, request_id, text) if self.prompt_builder else None
            messages = bundle.messages if bundle else [ChatMessage(role="system", content="你是 main agent，给出简洁可靠的内部结论。"), ChatMessage(role="user", content=text)]
            if self.capability_executor is None or not hasattr(self.model, "chat_complete"):
                return self.model.chat(messages).strip(), []
            return self._run_tool_loop(messages, intent_text=text)
        except LLMError as exc:
            return self._rule_reply(session_id, text), []

    async def _authoritative_reply_async(self, session_id: str, request_id: str, text: str) -> tuple[str, list[dict]]:
        if self.model is None or not hasattr(self.model, "chat_complete_async"):
            return self._authoritative_reply(session_id, request_id, text)
        try:
            bundle = self.prompt_builder.main_decision(session_id, request_id, text) if self.prompt_builder else None
            messages = bundle.messages if bundle else [ChatMessage(role="system", content="你是 main agent，给出简洁可靠的内部结论。"), ChatMessage(role="user", content=text)]
            if self.capability_executor is None:
                response = await self.model.chat_complete_async(messages)  # type: ignore[union-attr]
                return (response.content or "").strip(), []
            return await self._run_tool_loop_async(messages, intent_text=text)
        except LLMError as exc:
            return self._rule_reply(session_id, text), []

    def _rule_reply(self, session_id: str, text: str) -> str:
        lowered = text.lower()
        if any(key in text for key in ("工具", "能力")) or "tool" in lowered:
            caps = self.prompt_builder.capabilities.list_for_prompt(max_items=12) if self.prompt_builder and self.prompt_builder.capabilities else ""
            return "当前运行时能力主要有：\n" + caps if caps else "当前可以查任务、查记忆、安排 hook、发起受控后台任务。"
        if any(key in text for key in ("刚刚", "之前", "记录", "上下文")):
            lines = self.sessions.session_context_lines(session_id, include_compacted=False)[-8:]
            if not lines:
                return "当前这个会话里还没有可用记录。"
            return "我能看到当前会话最近这些记录：\n" + "\n".join(lines)
        if text.strip().startswith(("cd ", "/cd ")):
            path = text.strip().split(maxsplit=1)[1] if len(text.strip().split(maxsplit=1)) > 1 else "~"
            if self.capability_executor is not None:
                from advanced_agent.capability_executor import CapabilityRequest
                result = self.capability_executor.execute(CapabilityRequest("workdir_chdir", AgentRole.MAIN, {"path": path}))
                if result.ok:
                    return f"已切换工作目录到 `{result.data['cwd']}`；项目根目录推断为 `{result.data['project_root']}`。"
                return f"切换目录失败：{result.error}"
        if any(key in text for key in ("项目", "目录", "路径", "文件系统")) or any(key in lowered for key in ("cwd", "project")):
            if self.capability_executor is not None:
                from advanced_agent.capability_executor import CapabilityRequest
                result = self.capability_executor.execute(CapabilityRequest("project_info", AgentRole.MAIN, {}))
                if result.ok:
                    return f"当前运行目录是 `{result.data['cwd']}`；项目根目录推断为 `{result.data['project_root']}`。"
            return "我现在没有拿到项目路径。"
        if any(key in text for key in ("任务", "进度", "输出", "hook")) or any(key in lowered for key in ("task", "status", "tail", "hook")):
            if self.capability_executor is not None:
                from advanced_agent.capability_executor import CapabilityRequest
                result = self.capability_executor.execute(CapabilityRequest("task_list", AgentRole.MAIN, {"limit": 5}))
                if result.ok and result.data["tasks"]:
                    rows = result.data["tasks"]
                    return "最近任务：\n" + "\n".join(f"- {row['status']} {row['stage'] or '-'}: {row['goal'][:80]}" for row in rows)
            return "当前没有查到最近任务。"
        return "我看到了。这个请求暂时不需要启动后台任务；如果要我继续处理，可以直接说目标。"

    def _tool_choice_for_intent(self, text: str):
        lowered = text.lower()
        if text.strip().startswith(("cd ", "/cd ")):
            path = text.strip().split(maxsplit=1)[1] if len(text.strip().split(maxsplit=1)) > 1 else "~"
            return {"type": "function", "function": {"name": "workdir_chdir", "arguments": {"path": path}}}
        if any(key in text for key in ("项目", "目录", "路径", "工作路径", "文件系统")) or any(key in lowered for key in ("cwd", "project root", "workdir")):
            return {"type": "function", "function": {"name": "project_info"}}
        if any(key in text for key in ("工具", "能力")) or "tool" in lowered:
            return "auto"
        if any(key in text for key in ("刚刚", "之前", "记录", "上下文")):
            return "auto"
        if any(key in text for key in ("任务", "进度", "输出", "hook")) or any(key in lowered for key in ("task", "status", "tail", "hook")):
            return {"type": "function", "function": {"name": "task_list"}}
        return "auto"

    def _run_tool_loop(self, messages: list[ChatMessage], intent_text: str = "", max_tool_rounds: int = 3) -> tuple[str, list[dict]]:
        assert self.capability_executor is not None
        tools = OpenAIToolAdapter.tool_schemas([
            "task_state",
            "task_list",
            "task_tail",
            "task_history",
            "memory_search",
            "project_info",
            "workdir_chdir",
            "hook_schedule",
            "interrupt_request",
            "spawn_task",
        ])
        tool_records: list[dict] = []
        response = self.model.chat_complete(messages, tools=tools, tool_choice=self._tool_choice_for_intent(intent_text))  # type: ignore[union-attr]
        rounds = 0
        while response.tool_calls and rounds < max_tool_rounds:
            rounds += 1
            messages.append(ChatMessage(role="assistant", content=response.content, tool_calls=[call.to_openai_dict() for call in response.tool_calls]))
            for tool_call in response.tool_calls:
                req = OpenAIToolAdapter.request_from_tool_call(tool_call.to_openai_dict(), AgentRole.MAIN, now_ms=self.time.wall_ms())
                result = self.capability_executor.execute(req)
                tool_records.append({
                    "tool_call_id": tool_call.id,
                    "capability": req.capability,
                    "ok": result.ok,
                    "error": result.error,
                    "data": result.data,
                })
                tool_message = OpenAIToolAdapter.result_to_tool_message(result, tool_call_id=tool_call.id)
                messages.append(ChatMessage(role="tool", content=tool_message["content"], tool_call_id=tool_message["tool_call_id"]))
            response = self.model.chat_complete(messages, tools=tools, tool_choice="auto")  # type: ignore[union-attr]
        if response.tool_calls:
            tool_records.append({"capability": "tool_loop", "ok": False, "error": "max_tool_rounds_exceeded"})
        return (response.content or "主 agent 已完成工具检查，但模型没有返回文本结论。").strip(), tool_records

    async def _run_tool_loop_async(self, messages: list[ChatMessage], intent_text: str = "", max_tool_rounds: int = 3) -> tuple[str, list[dict]]:
        assert self.capability_executor is not None
        tools = OpenAIToolAdapter.tool_schemas([
            "task_state",
            "task_list",
            "task_tail",
            "task_history",
            "memory_search",
            "project_info",
            "workdir_chdir",
            "hook_schedule",
            "interrupt_request",
            "spawn_task",
        ])
        tool_records: list[dict] = []
        response = await self.model.chat_complete_async(messages, tools=tools, tool_choice=self._tool_choice_for_intent(intent_text))  # type: ignore[union-attr]
        rounds = 0
        while response.tool_calls and rounds < max_tool_rounds:
            rounds += 1
            messages.append(ChatMessage(role="assistant", content=response.content, tool_calls=[call.to_openai_dict() for call in response.tool_calls]))
            for tool_call in response.tool_calls:
                req = OpenAIToolAdapter.request_from_tool_call(tool_call.to_openai_dict(), AgentRole.MAIN, now_ms=self.time.wall_ms())
                result = await self.capability_executor.execute_async(req)
                tool_records.append({
                    "tool_call_id": tool_call.id,
                    "capability": req.capability,
                    "ok": result.ok,
                    "error": result.error,
                    "data": result.data,
                })
                tool_message = OpenAIToolAdapter.result_to_tool_message(result, tool_call_id=tool_call.id)
                messages.append(ChatMessage(role="tool", content=tool_message["content"], tool_call_id=tool_message["tool_call_id"]))
            response = await self.model.chat_complete_async(messages, tools=tools, tool_choice="auto")  # type: ignore[union-attr]
        if response.tool_calls:
            tool_records.append({"capability": "tool_loop", "ok": False, "error": "max_tool_rounds_exceeded"})
        return (response.content or "主 agent 已完成工具检查，但模型没有返回文本结论。").strip(), tool_records
