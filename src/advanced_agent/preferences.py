from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from advanced_agent.auto_memory_design import AutoMemoryPolicy, MemoryCandidateAction, MemoryEvidenceSource, ProfileDiffPatch
from advanced_agent.profile.writer import MajorModelMemoryWriter
from advanced_agent.memory_service import MemoryRecord, MemoryService
from advanced_agent.profile.observer import DeterministicProfileMaintainer, ProfileEvidence, ProfileMaintainer
from advanced_agent.stores.profile_store import ProfileStore, PromptOverlayStore
from advanced_agent.stores.session_store import SessionStore
from advanced_agent.time_service import TimeService


@dataclass(slots=True)
class PreferenceLimits:
    total_profile_chars: int = 1200
    category_chars: int = 280
    overlay_chars: int = 600
    max_vector_traits: int = 12
    recent_evidence_limit: int = 32
    maintenance_min_interval_ms: int = 10 * 60 * 1000
    maintenance_min_new_messages: int = 4
    major_write_min_new_messages: int = 24


class PreferenceWorker:
    """Maintain lightweight profile overlays from vector-memory traits.

    The durable user profile lives in vector memory. `user_profiles.summary` and
    prompt overlays are intentionally compact startup hints assembled from a few
    injectable traits; they are not the authoritative profile store.
    """

    def __init__(
        self,
        sessions: SessionStore,
        profiles: ProfileStore,
        overlays: PromptOverlayStore,
        time: TimeService,
        limits: PreferenceLimits | None = None,
        memory: MemoryService | None = None,
        policy: AutoMemoryPolicy | None = None,
        maintainer: ProfileMaintainer | None = None,
        major_writer: MajorModelMemoryWriter | None = None,
    ) -> None:
        self.sessions = sessions
        self.profiles = profiles
        self.overlays = overlays
        self.time = time
        self.limits = limits or PreferenceLimits()
        self.memory = memory
        self.policy = policy or AutoMemoryPolicy()
        self.maintainer = maintainer or DeterministicProfileMaintainer(category_chars=self.limits.category_chars)
        self.major_writer = major_writer or MajorModelMemoryWriter(None)

    def update_from_session(self, session_id: str, scope: str = "project:advanced_agent", *, allow_major_write: bool = True) -> str:
        evidence = self._recent_user_evidence(session_id)
        existing_traits = self._existing_traits(scope)
        if allow_major_write or self._should_run_profile_maintenance(session_id, scope, evidence):
            observer_patches = self.maintainer.propose(evidence=evidence, existing_traits=existing_traits, scope=scope)
            major_write_allowed = allow_major_write or self._should_run_major_write(session_id, scope, evidence)
            if major_write_allowed:
                patches = self._authorize_profile_patches(scope=scope, evidence=evidence, existing_traits=existing_traits, observer_patches=observer_patches)
            elif getattr(self.maintainer, "requires_major_model_write", False):
                patches = []
            else:
                patches = observer_patches
            self._apply_profile_patches(scope=scope, patches=patches)
            self._record_profile_maintenance_state(session_id, scope, evidence, major_write_allowed=major_write_allowed)

        lines = self._vector_profile_lines(scope)
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

    def _recent_user_evidence(self, session_id: str) -> list[ProfileEvidence]:
        rows = self.sessions.db.query_all(
            "SELECT id, role, content FROM messages WHERE session_id=? AND role IN ('user','codex_tail') ORDER BY created_at_ms DESC LIMIT ?",
            (session_id, self.limits.recent_evidence_limit),
        )
        evidence: list[ProfileEvidence] = []
        for row in reversed(rows):
            text = str(row["content"]).strip()
            if text:
                role = str(row["role"])
                if role == "codex_tail":
                    text = (
                        "[cleaned_codex_terminal_tail: mixed transcript; may include assistant/tool output. "
                        "Use only clearly user-originated preference/correction/workflow statements as profile evidence.]\n"
                        + text
                    )
                    source_strength = MemoryEvidenceSource.WRAPPER_INFERENCE
                else:
                    source_strength = MemoryEvidenceSource.USER_BEHAVIOR
                evidence.append(ProfileEvidence(text=text, message_id=row["id"], source_strength=source_strength))
        return evidence

    def _existing_traits(self, scope: str) -> list[MemoryRecord]:
        if self.memory is None:
            return []
        records: list[MemoryRecord] = []
        for type_ in ("preference", "workflow_habit", "user_trait"):
            records.extend(self.memory.recent(scope=scope, type=type_, limit=self.limits.max_vector_traits))
        seen: set[str] = set()
        unique: list[MemoryRecord] = []
        for record in records:
            if record.memory_id in seen:
                continue
            seen.add(record.memory_id)
            unique.append(record)
        return unique[: self.limits.max_vector_traits]

    def _should_run_profile_maintenance(self, session_id: str, scope: str, evidence: list[ProfileEvidence]) -> bool:
        if not evidence:
            return False
        state = self._profile_maintenance_state(session_id, scope)
        now = self.time.wall_ms()
        last_run_ms = int(state.get("last_run_ms", 0))
        last_message_id = str(state.get("last_message_id", ""))
        new_count = 0
        seen_last = not last_message_id
        for item in evidence:
            if item.message_id == last_message_id:
                seen_last = True
                new_count = 0
                continue
            if seen_last:
                new_count += 1
        if last_run_ms <= 0:
            return True
        if new_count >= self.limits.maintenance_min_new_messages:
            return True
        return now - last_run_ms >= self.limits.maintenance_min_interval_ms and new_count > 0

    def _should_run_major_write(self, session_id: str, scope: str, evidence: list[ProfileEvidence]) -> bool:
        state = self._profile_maintenance_state(session_id, scope)
        last_major_message_id = str(state.get("last_major_message_id", ""))
        if not evidence:
            return False
        new_count = 0
        seen_last = not last_major_message_id
        for item in evidence:
            if item.message_id == last_major_message_id:
                seen_last = True
                new_count = 0
                continue
            if seen_last:
                new_count += 1
        return new_count >= self.limits.major_write_min_new_messages

    def _profile_maintenance_state(self, session_id: str, scope: str) -> dict:
        row = self.overlays.db.query_one(
            "SELECT content FROM prompt_overlays WHERE scope=? AND target_agent=? AND category=? AND status='active' ORDER BY updated_at_ms DESC LIMIT 1",
            (scope, "_internal", self._profile_state_category(session_id)),
        )
        if row is None or not row["content"]:
            return {}
        try:
            metadata = json.loads(row["content"])
            return metadata if isinstance(metadata, dict) else {}
        except Exception:
            return {}

    def _record_profile_maintenance_state(self, session_id: str, scope: str, evidence: list[ProfileEvidence], *, major_write_allowed: bool = False) -> None:
        if not evidence:
            return
        last_message_id = evidence[-1].message_id or ""
        now = self.time.wall_ms()
        previous = self._profile_maintenance_state(session_id, scope)
        payload = {
            "session_id": session_id,
            "last_message_id": last_message_id,
            "last_run_ms": now,
            "last_major_message_id": previous.get("last_major_message_id", ""),
            "last_major_run_ms": previous.get("last_major_run_ms", 0),
        }
        if major_write_allowed:
            payload["last_major_message_id"] = last_message_id
            payload["last_major_run_ms"] = now
        self.overlays.replace_overlay(
            scope,
            "_internal",
            self._profile_state_category(session_id),
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            now,
            priority=0,
            max_chars=1000,
            source="profile_maintenance",
        )

    def _profile_state_category(self, session_id: str) -> str:
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:24]
        return f"profile_maintenance_state:{digest}"

    def _authorize_profile_patches(
        self,
        *,
        scope: str,
        evidence: list[ProfileEvidence],
        existing_traits: list[MemoryRecord],
        observer_patches: list[ProfileDiffPatch],
    ) -> list[ProfileDiffPatch]:
        if getattr(self.maintainer, "requires_major_model_write", False):
            decision = self.major_writer.decide_profile_patches(
                scope=scope,
                evidence=evidence,
                existing_traits=existing_traits,
                observer_patches=observer_patches,
            )
            return decision.patches
        return observer_patches

    def _apply_profile_patches(self, *, scope: str, patches: list[ProfileDiffPatch]) -> None:
        if self.memory is None:
            return
        now = self.time.wall_ms()
        for patch in patches:
            if patch.action in {MemoryCandidateAction.IGNORE, MemoryCandidateAction.CANDIDATE, MemoryCandidateAction.ESCALATE}:
                continue
            if patch.action in {MemoryCandidateAction.REMOVE, MemoryCandidateAction.WEAKEN}:
                if patch.target_memory_id:
                    self.memory.deactivate(patch.target_memory_id, status="inactive", now_ms=now)
                continue
            if not patch.summary:
                continue
            source_strength = str(patch.source_strength or MemoryEvidenceSource.WRAPPER_INFERENCE)
            if not self.policy.can_store_candidate(confidence=patch.confidence, source=source_strength):
                continue
            metadata = dict(patch.metadata or {})
            metadata.setdefault("maintainer", "wrapper")
            metadata.setdefault("kind", "profile_trait" if patch.action != MemoryCandidateAction.ADD or not patch.summary.startswith("[profile_evidence]") else "profile_evidence")
            metadata.setdefault("evidence", patch.evidence[:500])
            if patch.action == MemoryCandidateAction.UPDATE:
                metadata.setdefault("action", "update")
            digest = hashlib.sha256(f"{scope}:{patch.action}:{patch.target_memory_id}:{patch.summary}:{patch.evidence}".encode("utf-8")).hexdigest()[:24]
            source_id = f"wrapper_profile:{scope}:{metadata.get('kind')}:{digest}"
            memory_type = str(metadata.get("memory_type") or self._memory_type_for_patch(patch))
            content = self._content_for_patch(patch, metadata)
            self.memory.write(
                summary=patch.summary[: self.limits.category_chars],
                content=content,
                scope=scope,
                type=memory_type,
                source_type="wrapper_profile",
                source_id=source_id,
                importance=patch.importance,
                confidence=patch.confidence,
                source_strength=source_strength,
                stability=patch.stability,
                last_evidence_at_ms=now,
                supersedes_id=patch.target_memory_id if patch.action in {MemoryCandidateAction.UPDATE, MemoryCandidateAction.SUPERSEDE} else None,
                metadata=metadata,
                agent_role="memory",
            )

    def _memory_type_for_patch(self, patch: ProfileDiffPatch) -> str:
        kind = str((patch.metadata or {}).get("kind", ""))
        if kind == "workflow_habit":
            return "workflow_habit"
        if kind == "preference":
            return "preference"
        return "user_trait"

    def _content_for_patch(self, patch: ProfileDiffPatch, metadata: dict) -> str:
        evidence = patch.evidence[:500]
        if evidence:
            return f"Wrapper-maintained user profile record. Evidence: {evidence}"
        return f"Wrapper-maintained user profile record. Kind: {metadata.get('kind', 'profile_trait')}"

    def _vector_profile_lines(self, scope: str) -> list[str]:
        records = self._existing_traits(scope)
        lines: list[str] = []
        seen: set[str] = set()
        for record in records:
            if not self.policy.can_inject(confidence=record.confidence, importance=record.importance, source=record.source_strength):
                continue
            key = record.summary.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            lines.append(key[: self.limits.category_chars])
            if len(lines) >= self.policy.query_trait_limit:
                break
        return lines

    def _overlay_for_main(self, summary: str) -> str:
        return (
            "Lightweight startup user-profile hints from vector memory; not the full profile. "
            "Use context_get for query-specific traits and prefer newer direct user messages on conflict:\n" + summary
        )[: self.limits.overlay_chars]

    def _overlay_for_interactive(self, summary: str) -> str:
        return (
            "Lightweight startup user-profile hints from vector memory; keep replies aligned "
            "but do not expose profile machinery:\n" + summary
        )[: self.limits.overlay_chars]
