from __future__ import annotations

import json
from typing import Protocol

from advanced_agent.llm import ChatMessage, LLMError, OpenAICompatibleClient
from advanced_agent.vectors import MemoryAlignment
from advanced_agent.memory_facets import normalize_facets


class MemoryAligner(Protocol):
    def labels_for(self, text: str, agent_role: str = "main") -> dict[str, str]: ...


class LLMMemoryAlignment:
    """LLM-assisted memory labeler with deterministic fallback.

    The LLM does not write memory directly. It only proposes retrieval labels;
    MemoryIndexer remains the durable write path.
    """

    def __init__(self, model: OpenAICompatibleClient | None, fallback: MemoryAlignment | None = None, max_label_chars: int = 500) -> None:
        self.model = model
        self.fallback = fallback or MemoryAlignment()
        self.max_label_chars = max_label_chars

    def labels_for(self, text: str, agent_role: str = "main") -> dict[str, str]:
        if self.model is None:
            return normalize_facets(self.fallback.labels_for(text, agent_role=agent_role), summary=text[:200], content=text)
        try:
            raw = self.model.chat([
                ChatMessage(role="system", content=(
                    "You are the Advanced Agent vector-memory keyword labeler. Output only a JSON object; do not explain. "
                    "Generate compact retrieval labels for a vector database. Prefer keys: semantic, keywords, workspace. "
                    "keywords should contain high-value future search terms and short phrases, not prose categories. "
                    "workspace is only for concrete paths/modules/projects visible in the text. Stay factual; omit unsupported fields."
                )),
                ChatMessage(role="user", content=f"agent_role={agent_role}\ntext:\n{text[:4000]}"),
            ])
            parsed = self._parse_json_object(raw)
            labels = normalize_facets(self.fallback.labels_for(text, agent_role=agent_role), summary=text[:200], content=text)
            for key, value in parsed.items():
                if isinstance(key, str) and isinstance(value, str) and value.strip():
                    labels[key] = value.strip()[: self.max_label_chars]
            return normalize_facets(labels, summary=text[:200], content=text)
        except (LLMError, ValueError, TypeError, json.JSONDecodeError):
            return normalize_facets(self.fallback.labels_for(text, agent_role=agent_role), summary=text[:200], content=text)

    def _parse_json_object(self, raw: str) -> dict:
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:].strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end >= start:
            text = text[start : end + 1]
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("memory label response must be a JSON object")
        return parsed
