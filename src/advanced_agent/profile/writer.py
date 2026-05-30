from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from advanced_agent.auto_memory_design import MemoryCandidateAction, MemoryEvidenceSource, ProfileDiffPatch, PROFILE_DIFF_PROMPT_CONTRACT
from advanced_agent.llm import ChatMessage, LLMError, OpenAICompatibleClient, ToolCall
from advanced_agent.memory_service import MemoryRecord
from advanced_agent.profile.observer import ProfileEvidence


MEMORY_WRITE_TOOL_NAME = "memory_profile_patch"


@dataclass(slots=True)
class MemoryWriteDecision:
    patches: list[ProfileDiffPatch]
    used_model: bool
    reason: str = ""


class MajorModelMemoryWriter:
    """Authoritative memory writer that requires tool-call shaped model output.

    The small model may observe and propose candidates, but durable profile writes
    should be decided by a stronger model using a tool schema. If no major model
    is configured, this writer refuses to create distilled traits.
    """

    def __init__(self, model: OpenAICompatibleClient | None, max_tool_calls: int = 8) -> None:
        self.model = model
        self.max_tool_calls = max_tool_calls

    def decide_profile_patches(
        self,
        *,
        scope: str,
        evidence: list[ProfileEvidence],
        existing_traits: list[MemoryRecord],
        observer_patches: list[ProfileDiffPatch],
    ) -> MemoryWriteDecision:
        if self.model is None:
            return MemoryWriteDecision(patches=[], used_model=False, reason="major_model_not_configured")
        try:
            response = self.model.chat_complete(
                [
                    ChatMessage(role="system", content=self._system_prompt()),
                    ChatMessage(role="user", content=self._input_json(scope, evidence, existing_traits, observer_patches)),
                ],
                tools=[self.tool_schema()],
                tool_choice={"type": "function", "function": {"name": MEMORY_WRITE_TOOL_NAME}},
            )
            patches = self._patches_from_tool_calls(response.tool_calls)
            return MemoryWriteDecision(patches=patches[: self.max_tool_calls], used_model=True, reason="tool_calls")
        except (LLMError, ValueError, TypeError, json.JSONDecodeError):
            return MemoryWriteDecision(patches=[], used_model=False, reason="major_model_failed")

    def _system_prompt(self) -> str:
        return (
            "You are the authoritative Advanced Agent memory writer. Durable memory writes are high precision. "
            "Use the provided tool for every approved profile-memory patch; do not write prose. "
            "Small-model observer suggestions are only hints and may hallucinate. "
            "Only user-originated evidence or verified tool outcomes may justify user profile traits.\n"
            + PROFILE_DIFF_PROMPT_CONTRACT
        )

    def _input_json(
        self,
        scope: str,
        evidence: list[ProfileEvidence],
        existing_traits: list[MemoryRecord],
        observer_patches: list[ProfileDiffPatch],
    ) -> str:
        payload = {
            "scope": scope,
            "evidence": [
                {"text": item.text[:1200], "message_id": item.message_id, "source_strength": item.source_strength}
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
            "small_model_observer_suggestions": [self._patch_to_dict(patch) for patch in observer_patches[:10]],
            "instruction": "Call memory_profile_patch once per approved durable write/update/remove. Call no tools if no durable memory change is justified.",
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _patch_to_dict(self, patch: ProfileDiffPatch) -> dict[str, Any]:
        return {
            "action": str(patch.action),
            "summary": patch.summary,
            "target_memory_id": patch.target_memory_id,
            "confidence": patch.confidence,
            "importance": patch.importance,
            "stability": patch.stability,
            "source_strength": str(patch.source_strength),
            "evidence": patch.evidence,
            "metadata": patch.metadata,
        }

    def _patches_from_tool_calls(self, tool_calls: list[ToolCall]) -> list[ProfileDiffPatch]:
        patches: list[ProfileDiffPatch] = []
        for call in tool_calls:
            if call.name != MEMORY_WRITE_TOOL_NAME:
                continue
            args = json.loads(call.arguments or "{}")
            patch = self._patch_from_args(args)
            if patch.action != MemoryCandidateAction.IGNORE:
                patches.append(patch)
        return patches

    def _patch_from_args(self, args: dict[str, Any]) -> ProfileDiffPatch:
        action = self._action(str(args.get("action", "ignore")))
        return ProfileDiffPatch(
            action=action,
            summary=str(args.get("summary") or "").strip(),
            target_memory_id=str(args["target_memory_id"]).strip() if args.get("target_memory_id") else None,
            confidence=self._float(args.get("confidence"), 0.0),
            importance=self._float(args.get("importance"), 0.0),
            stability=str(args.get("stability") or "normal")[:40],
            source_strength=str(args.get("source_strength") or MemoryEvidenceSource.EXPLICIT_USER)[:80],
            evidence=str(args.get("evidence") or "").strip()[:1000],
            metadata=args.get("metadata") if isinstance(args.get("metadata"), dict) else {},
        )

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

    def tool_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": MEMORY_WRITE_TOOL_NAME,
                "description": "Approve one durable user-profile memory patch grounded in provided evidence.",
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "action": {"type": "string", "enum": ["add", "update", "supersede", "remove", "ignore"]},
                        "target_memory_id": {"type": "string", "description": "Existing memory id for update/supersede/remove; omit for add."},
                        "summary": {"type": "string", "description": "Short searchable memory summary."},
                        "evidence": {"type": "string", "description": "Short user/tool evidence that justifies the patch."},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "importance": {"type": "number", "minimum": 0, "maximum": 1},
                        "stability": {"type": "string", "enum": ["situational", "normal", "stable"]},
                        "source_strength": {"type": "string", "enum": ["explicit_user", "user_correction", "user_behavior", "tool_verified"]},
                        "metadata": {
                            "type": "object",
                            "additionalProperties": True,
                            "properties": {
                                "kind": {"type": "string", "enum": ["profile_trait", "preference", "workflow_habit", "profile_evidence"]},
                                "memory_type": {"type": "string", "enum": ["user_trait", "preference", "workflow_habit"]},
                                "category": {"type": "string"},
                            },
                        },
                    },
                    "required": ["action", "summary", "evidence", "confidence", "importance", "stability", "source_strength"],
                },
            },
        }
