from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from advanced_agent.config import ModelConfig


@dataclass(slots=True)
class ChatMessage:
    role: str
    content: str | None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None

    def to_openai_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_call_id is not None:
            data["tool_call_id"] = self.tool_call_id
        if self.tool_calls is not None:
            data["tool_calls"] = self.tool_calls
        return data


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: str
    type: str = "function"

    def to_openai_dict(self) -> dict[str, Any]:
        return {"id": self.id, "type": self.type, "function": {"name": self.name, "arguments": self.arguments}}


@dataclass(slots=True)
class ChatResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class LLMError(RuntimeError):
    pass


class OpenAICompatibleClient:
    """Minimal OpenAI-compatible chat completions client.

    It intentionally avoids SDK lock-in. Any backend exposing
    `/chat/completions` with bearer auth can be configured by `.env.json`.
    """

    def __init__(self, config: ModelConfig) -> None:
        self.config = config

    def chat(self, messages: list[ChatMessage]) -> str:
        response = self.chat_complete(messages)
        return response.content or ""

    def chat_complete(self, messages: list[ChatMessage], tools: list[dict[str, Any]] | None = None, tool_choice: str | dict[str, Any] | None = None) -> ChatResponse:
        payload = self._payload(messages, tools=tools, tool_choice=tool_choice)
        body = self._post_sync(payload)
        return self._parse_response(body)

    async def chat_complete_async(self, messages: list[ChatMessage], tools: list[dict[str, Any]] | None = None, tool_choice: str | dict[str, Any] | None = None) -> ChatResponse:
        payload = self._payload(messages, tools=tools, tool_choice=tool_choice)
        body = await self._post_async(payload)
        return self._parse_response(body)

    def _payload(self, messages: list[ChatMessage], tools: list[dict[str, Any]] | None = None, tool_choice: str | dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "model": self.config.model,
            "messages": [m.to_openai_dict() for m in messages],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            **({"tools": tools} if tools else {}),
            **({"tool_choice": tool_choice} if tool_choice is not None else {}),
        }

    def _headers(self) -> dict[str, str]:
        api_key = self.config.resolved_api_key()
        if not api_key:
            raise LLMError(f"missing api key for model config {self.config.name}")
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "OpenAI/Python 1.0",
        }

    def _post_sync(self, payload: dict[str, Any]) -> str:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMError(f"LLM HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc
        return body

    async def _post_async(self, payload: dict[str, Any]) -> str:
        try:
            import httpx
        except ModuleNotFoundError as exc:  # pragma: no cover
            raise LLMError("httpx is required for async LLM calls. Install with: pip install httpx") from exc
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds, headers=self._headers()) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPStatusError as exc:
            raise LLMError(f"LLM HTTP {exc.response.status_code}: {exc.response.text}") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc

    def _parse_response(self, body: str) -> ChatResponse:
        parsed = json.loads(body)
        try:
            message = parsed["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unexpected LLM response: {body[:500]}") from exc
        tool_calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function", {})
            tool_calls.append(
                ToolCall(
                    id=str(call.get("id", "")),
                    type=str(call.get("type", "function")),
                    name=str(function.get("name", "")),
                    arguments=str(function.get("arguments", "{}")),
                )
            )
        return ChatResponse(content=message.get("content"), tool_calls=tool_calls, raw=parsed)


class ModelRouter:
    def __init__(self, role_clients: dict[str, OpenAICompatibleClient]) -> None:
        self.role_clients = role_clients

    @classmethod
    def from_config(cls, config) -> "ModelRouter":
        clients = {}
        for role in ("interactive_model", "main_model", "audit_model", "memory_model", "memory_write_model"):
            model = config.model_for_role(role)
            if model is not None:
                clients[role] = OpenAICompatibleClient(model)
        return cls(clients)

    def client_for(self, role: str) -> OpenAICompatibleClient | None:
        return self.role_clients.get(role)
