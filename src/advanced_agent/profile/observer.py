from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from advanced_agent.auto_memory_design import MemoryCandidateAction, MemoryEvidenceSource, ProfileDiffPatch, PROFILE_DIFF_PROMPT_CONTRACT
from advanced_agent.llm import ChatMessage, LLMError, OpenAICompatibleClient
from advanced_agent.memory_service import MemoryRecord


@dataclass(slots=True)
class ProfileEvidence:
    text: str
    message_id: str | None = None
    source_strength: str = MemoryEvidenceSource.USER_BEHAVIOR


class ProfileMaintainer(Protocol):
    def propose(self, *, evidence: list[ProfileEvidence], existing_traits: list[MemoryRecord], scope: str) -> list[ProfileDiffPatch]: ...

    @property
    def requires_major_model_write(self) -> bool: ...


class DeterministicProfileMaintainer:
    """Fallback profile maintainer.

    It stores user-originated evidence as bounded vector-memory records without
    semantic keyword classification. The LLM maintainer can later promote these
    evidence notes into distilled traits.
    """

    requires_major_model_write = False

    def __init__(self, category_chars: int = 280) -> None:
        self.category_chars = category_chars

    def propose(self, *, evidence: list[ProfileEvidence], existing_traits: list[MemoryRecord], scope: str) -> list[ProfileDiffPatch]:
        patches: list[ProfileDiffPatch] = []
        for item in evidence:
            compact = " ".join(item.text.split())
            if not compact:
                continue
            patches.append(ProfileDiffPatch(
                action=MemoryCandidateAction.ADD,
                summary=f"[profile_evidence] {compact[: self.category_chars]}",
                confidence=0.84,
                importance=0.62,
                stability="normal",
                source_strength=item.source_strength,
                evidence=compact[:500],
                metadata={"category": "profile_evidence", "kind": "profile_evidence", "maintainer": "wrapper", "message_id": item.message_id},
            ))
        return patches


class LLMProfileMaintainer:
    """Small-model user-profile observer.

    It may propose candidate patches, but PreferenceWorker must route real
    durable writes through the major-model tool-call writer.
    """

    requires_major_model_write = True

    def __init__(self, model: OpenAICompatibleClient | None, fallback: ProfileMaintainer | None = None, max_patches: int = 6) -> None:
        self.model = model
        self.fallback = fallback or DeterministicProfileMaintainer()
        self.max_patches = max_patches

    def propose(self, *, evidence: list[ProfileEvidence], existing_traits: list[MemoryRecord], scope: str) -> list[ProfileDiffPatch]:
        if self.model is None or not evidence:
            return self.fallback.propose(evidence=evidence, existing_traits=existing_traits, scope=scope)
        try:
            raw = self.model.chat([
                ChatMessage(role="system", content=(
                    "You are the Advanced Agent small user-profile memory maintainer. "
                    "Output only a JSON object with a patches array; do not explain.\n"
                    + PROFILE_DIFF_PROMPT_CONTRACT
                )),
                ChatMessage(role="user", content=self._input_json(scope, evidence, existing_traits)),
            ])
            patches = self._parse_patches(raw)
            return patches[: self.max_patches] or self.fallback.propose(evidence=evidence, existing_traits=existing_traits, scope=scope)
        except (LLMError, ValueError, TypeError, json.JSONDecodeError):
            return self.fallback.propose(evidence=evidence, existing_traits=existing_traits, scope=scope)

    def _input_json(self, scope: str, evidence: list[ProfileEvidence], existing_traits: list[MemoryRecord]) -> str:
        payload = {
            "scope": scope,
            "evidence": [
                {"text": item.text[:1000], "message_id": item.message_id, "source_strength": item.source_strength}
                for item in evidence[-8:]
            ],
            "existing_traits": [
                {
                    "memory_id": record.memory_id,
                    "type": record.type,
                    "summary": record.summary,
                    "content": (record.content or "")[:1000],
                    "confidence": record.confidence,
                    "importance": record.importance,
                    "source_strength": record.source_strength,
                    "stability": record.stability,
                    "metadata": record.metadata or {},
                }
                for record in existing_traits[:20]
            ],
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _parse_patches(self, raw: str) -> list[ProfileDiffPatch]:
        parsed = self._parse_json_object(raw)
        items = parsed.get("patches", parsed.get("actions", []))
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            raise ValueError("profile maintainer response must contain patches array")
        patches: list[ProfileDiffPatch] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            action = self._action(str(item.get("action", "ignore")))
            patch = ProfileDiffPatch(
                action=action,
                summary=str(item.get("summary") or "").strip(),
                target_memory_id=str(item["target_memory_id"]).strip() if item.get("target_memory_id") else None,
                confidence=self._float(item.get("confidence"), 0.0),
                importance=self._float(item.get("importance"), 0.0),
                stability=str(item.get("stability") or "normal")[:40],
                source_strength=str(item.get("source_strength") or MemoryEvidenceSource.WRAPPER_INFERENCE)[:80],
                evidence=str(item.get("evidence") or item.get("difference") or "").strip()[:1000],
                metadata=item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
            )
            if patch.action == MemoryCandidateAction.IGNORE:
                continue
            patches.append(patch)
        return patches

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
            raise ValueError("profile maintainer response must be a JSON object")
        return parsed

    def _action(self, raw: str) -> MemoryCandidateAction:
        normalized = raw.strip().lower()
        aliases = {"no_change": "ignore", "strengthen": "update", "delete": "remove"}
        normalized = aliases.get(normalized, normalized)
        try:
            return MemoryCandidateAction(normalized)
        except ValueError:
            return MemoryCandidateAction.IGNORE

    def _float(self, value, default: float) -> float:
        try:
            return max(0.0, min(float(value), 1.0))
        except (TypeError, ValueError):
            return default
