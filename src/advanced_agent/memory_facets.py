from __future__ import annotations

from dataclasses import dataclass, field
import re


DEFAULT_MEMORY_FACETS: tuple[str, ...] = (
    "semantic",
    "workstream",
    "workspace",
    "time",
    "content_type",
    "topic_keywords",
    "free_keywords",
    "methodology",
    "project_feature",
    "implementation",
    "decision",
    "preference",
    "procedure",
    "risk",
    "handoff",
    "chat",
    "agent_relevance",
)


QUERY_PROFILE_WEIGHTS: dict[str, dict[str, float]] = {
    "auto": {},
    "general": {"semantic": 1.0, "topic_keywords": 0.7, "free_keywords": 0.6, "workstream": 0.45, "agent_relevance": 0.3},
    "design": {"decision": 1.0, "workstream": 0.8, "methodology": 0.7, "topic_keywords": 0.65, "project_feature": 0.5, "semantic": 0.3},
    "project": {"workstream": 1.0, "topic_keywords": 0.85, "workspace": 0.7, "project_feature": 0.6, "implementation": 0.5, "handoff": 0.5},
    "methodology": {"methodology": 1.0, "topic_keywords": 0.7, "preference": 0.6, "procedure": 0.5, "semantic": 0.3},
    "preference": {"preference": 1.0, "methodology": 0.7, "workstream": 0.4, "agent_relevance": 0.4},
    "procedure": {"procedure": 1.0, "topic_keywords": 0.75, "implementation": 0.7, "risk": 0.4, "semantic": 0.3},
    "risk": {"risk": 1.0, "topic_keywords": 0.7, "decision": 0.5, "procedure": 0.4},
    "handoff": {"handoff": 1.0, "workstream": 0.7, "topic_keywords": 0.65, "implementation": 0.5, "time": 0.4},
    "chat": {"chat": 1.0, "content_type": 0.7, "topic_keywords": 0.6, "semantic": 0.4, "time": 0.3},
    "recent": {"time": 1.0, "handoff": 0.6, "chat": 0.4, "workstream": 0.3, "topic_keywords": 0.3},
}


KIND_DEFAULT_FACETS: dict[str, tuple[str, ...]] = {
    "decision": ("semantic", "workstream", "content_type", "topic_keywords", "decision", "methodology", "agent_relevance"),
    "user_preference": ("semantic", "workstream", "content_type", "topic_keywords", "preference", "methodology", "agent_relevance"),
    "preference": ("semantic", "workstream", "content_type", "topic_keywords", "preference", "methodology", "agent_relevance"),
    "project_state": ("semantic", "workstream", "workspace", "project_feature", "topic_keywords", "handoff", "time", "agent_relevance"),
    "session_summary": ("semantic", "workstream", "content_type", "topic_keywords", "handoff", "chat", "time", "agent_relevance"),
    "procedure": ("semantic", "workstream", "content_type", "topic_keywords", "procedure", "implementation", "risk", "agent_relevance"),
    "warning": ("semantic", "workstream", "content_type", "topic_keywords", "risk", "procedure", "agent_relevance"),
    "handoff": ("semantic", "workstream", "workspace", "content_type", "topic_keywords", "handoff", "time", "agent_relevance"),
    "chat": ("semantic", "workstream", "content_type", "topic_keywords", "chat", "time"),
    "codex_interactive_log": ("semantic", "workspace", "content_type", "topic_keywords", "implementation", "time"),
}


def normalize_facets(facets: dict[str, str] | None, *, summary: str, content: str, type_: str = "note", metadata: dict | None = None) -> dict[str, str]:
    """Return bounded multi-dimensional retrieval facets for a memory record.

    sqlite-vec v0 stores one vector row per facet.  The facet names intentionally
    mirror Qdrant-style named vectors so the higher-level memory model can later
    migrate without changing callers.
    """

    metadata = metadata or {}
    text = (content or summary).strip()
    keywords = extract_keywords(" ".join([summary, text]), max_keywords=24)
    keyword_text = ", ".join(keywords)
    workstream = _join_nonempty("workstream/topic context", metadata.get("workstream"), metadata.get("topic"), metadata.get("project"), metadata.get("scope"), summary)
    workspace = _join_nonempty("workspace/filesystem context", metadata.get("workspace"), metadata.get("cwd"), metadata.get("project_root"), metadata.get("path"), metadata.get("module"), metadata.get("scope"))
    content_type = _join_nonempty("content category", type_, metadata.get("content_type"), _infer_content_type(type_, text))
    base = {
        "semantic": text,
        "workstream": workstream,
        "workspace": workspace,
        "time": _join_nonempty("time/recency context", metadata.get("time"), metadata.get("created_at_ms"), summary),
        "content_type": content_type,
        "topic_keywords": _join_nonempty("topic keywords", keyword_text),
        "free_keywords": keyword_text,
        "methodology": _join_nonempty("methodology/design habit", summary, text),
        "project_feature": _join_nonempty("project feature/module", metadata.get("feature"), metadata.get("module"), summary),
        "implementation": _join_nonempty("implementation detail/code/tool", summary, text),
        "decision": _join_nonempty("decision/confirmed constraint", summary, text),
        "preference": _join_nonempty("user preference/collaboration style", summary, text),
        "procedure": _join_nonempty("reusable procedure/workflow", summary, text),
        "risk": _join_nonempty("risk/warning/failure mode", summary, text),
        "handoff": _join_nonempty("handoff/current progress/next step", summary, text),
        "chat": _join_nonempty("conversation/chat context", summary, text),
        "agent_relevance": _join_nonempty("relevant to future agent behavior", summary, text),
    }
    selected = set(KIND_DEFAULT_FACETS.get(type_, ("semantic", "workstream", "agent_relevance")))
    selected.update((facets or {}).keys())
    selected.add("semantic")
    selected.update(("workstream", "content_type", "topic_keywords", "free_keywords"))
    if any(metadata.get(key) for key in ("workspace", "cwd", "project_root", "path", "module")):
        selected.add("workspace")
    result: dict[str, str] = {}
    for name in DEFAULT_MEMORY_FACETS:
        if name not in selected:
            continue
        value = (facets or {}).get(name) or base[name]
        value = str(value).strip()
        if value:
            result[name] = value[:1200]
    return result


def extract_keywords(text: str, max_keywords: int = 24) -> list[str]:
    """Extract a bounded but variable-length keyword list for hybrid retrieval."""

    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_./+-]{2,}|[\u4e00-\u9fff]{2,}", text)
    stop = {
        "the", "and", "for", "with", "that", "this", "from", "into", "when", "then", "than",
        "should", "would", "could", "about", "through", "there", "their", "memory", "context",
        "advanced", "agent",
    }
    seen: set[str] = set()
    scored: list[tuple[int, int, str]] = []
    for index, token in enumerate(tokens):
        normalized = token.strip(".,:;()[]{}<>").lower()
        if not normalized or normalized in stop or len(normalized) < 3:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        score = 0
        if any(ch in normalized for ch in "_./+-"):
            score += 3
        if any(ch.isdigit() for ch in normalized):
            score += 2
        if token[:1].isupper():
            score += 1
        score += min(len(normalized), 20)
        scored.append((score, -index, normalized))
    scored.sort(reverse=True)
    return [token for _, _, token in scored[:max_keywords]]


def _infer_content_type(type_: str, text: str) -> str:
    lowered = text.lower()
    if type_ in {"decision", "preference", "procedure", "warning", "handoff", "chat", "session_summary", "project_state"}:
        return type_
    if any(token in lowered for token in ("decide", "decision", "confirmed", "constraint")):
        return "decision"
    if any(token in lowered for token in ("prefer", "style", "habit", "likes")):
        return "preference"
    if any(token in lowered for token in ("steps", "workflow", "procedure", "how to")):
        return "procedure"
    if any(token in lowered for token in ("risk", "warning", "avoid", "failure", "pitfall")):
        return "warning"
    if any(token in lowered for token in ("handoff", "progress", "resume", "continue", "next step")):
        return "handoff"
    return type_ or "note"


def infer_query_profile(query: str, explicit: str = "auto") -> str:
    if explicit and explicit != "auto":
        return explicit
    q = query.lower()
    design_markers = ("control", "plane", "schema", "decision", "architecture", "design", "tradeoff", "abstraction")
    if any(token in q for token in design_markers):
        return "design"
    if any(token in q for token in ("preference", "style", "habit", "likes", "collaboration")):
        return "preference"
    if any(token in q for token in ("procedure", "workflow", "how to", "steps", "process")):
        return "procedure"
    if any(token in q for token in ("warning", "risk", "pitfall", "avoid", "failure")):
        return "risk"
    if any(token in q for token in ("handoff", "progress", "continue", "resume", "next step")):
        return "handoff"
    if any(token in q for token in ("today", "recent", "latest", "last time", "just now")):
        return "recent"
    if any(token in q for token in ("chat", "conversation", "discussion")):
        return "chat"
    return "general"


def facet_weights_for_profile(profile: str, overrides: dict[str, float] | None = None) -> dict[str, float]:
    weights = dict(QUERY_PROFILE_WEIGHTS.get(profile, QUERY_PROFILE_WEIGHTS["general"]))
    if overrides:
        for key, value in overrides.items():
            if key in DEFAULT_MEMORY_FACETS and value > 0:
                weights[key] = float(value)
    if not weights:
        weights = dict(QUERY_PROFILE_WEIGHTS["general"])
    return weights


@dataclass(slots=True)
class RawTailLine:
    created_at_ms: int
    role: str
    text: str
    source: str
    request_id: str | None = None
    seq: int | None = None

    def format(self, max_chars: int = 800) -> str:
        text = self.text[:max_chars]
        return f"{self.created_at_ms} {self.source}/{self.role}: {text}"


def _join_nonempty(prefix: str, *parts) -> str:
    values = [str(part).strip() for part in parts if part is not None and str(part).strip()]
    return f"{prefix}: " + " | ".join(values)
