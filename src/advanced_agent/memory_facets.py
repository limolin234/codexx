from __future__ import annotations

from dataclasses import dataclass, field
import re


# Keep the vector-facing label taxonomy small.  The high-value part is the
# LLM-generated retrieval text/keywords, not a large fixed ontology.
DEFAULT_MEMORY_FACETS: tuple[str, ...] = (
    "semantic",
    "keywords",
    "workspace",
)


QUERY_PROFILE_WEIGHTS: dict[str, dict[str, float]] = {
    "auto": {},
    "general": {"keywords": 1.0, "semantic": 0.65, "workspace": 0.25},
    "design": {"keywords": 1.0, "semantic": 0.55, "workspace": 0.25},
    "project": {"keywords": 1.0, "workspace": 0.75, "semantic": 0.45},
    "methodology": {"keywords": 1.0, "semantic": 0.55},
    "preference": {"keywords": 1.0, "semantic": 0.5},
    "procedure": {"keywords": 1.0, "semantic": 0.55, "workspace": 0.2},
    "risk": {"keywords": 1.0, "semantic": 0.55},
    "handoff": {"keywords": 1.0, "semantic": 0.5, "workspace": 0.35},
    "chat": {"keywords": 1.0, "semantic": 0.5},
    "recent": {"keywords": 0.9, "semantic": 0.4, "workspace": 0.3},
}


KIND_DEFAULT_FACETS: dict[str, tuple[str, ...]] = {
    "decision": ("semantic", "keywords"),
    "user_preference": ("semantic", "keywords"),
    "preference": ("semantic", "keywords"),
    "project_state": ("semantic", "keywords", "workspace"),
    "session_summary": ("semantic", "keywords"),
    "procedure": ("semantic", "keywords"),
    "warning": ("semantic", "keywords"),
    "handoff": ("semantic", "keywords", "workspace"),
    "chat": ("semantic", "keywords"),
    "codex_interactive_log": ("semantic", "keywords", "workspace"),
}


SEMANTIC_HINTS: dict[str, str] = {
    "decision": "decision/confirmed constraint",
    "preference": "user preference/collaboration style",
    "user_preference": "user preference/collaboration style",
    "handoff": "handoff/current progress/next step",
    "procedure": "reusable procedure/workflow",
    "warning": "risk/warning/failure mode",
    "project_state": "project state/current implementation",
    "session_summary": "session summary",
    "chat": "conversation context",
    "codex_interactive_log": "codex interactive log",
}


def normalize_facets(facets: dict[str, str] | None, *, summary: str, content: str, type_: str = "note", metadata: dict | None = None) -> dict[str, str]:
    """Return a compact set of vector-memory labels.

    The database may still store one vector row per label, but new memories use
    a small contract: semantic text, LLM/rule-generated keywords, and optional
    workspace text.  This keeps retrieval cheap and makes label quality come
    from the LLM-generated keyword/retrieval text instead of a large hard-coded
    facet taxonomy.
    """

    metadata = metadata or {}
    supplied = facets or {}
    text = (content or summary).strip()
    keyword_text = _keyword_text(supplied, summary, text)
    semantic_prefix = SEMANTIC_HINTS.get(type_, type_ or "memory")
    workspace = _join_nonempty(
        "workspace/filesystem context",
        metadata.get("workspace"),
        metadata.get("cwd"),
        metadata.get("project_root"),
        metadata.get("path"),
        metadata.get("module"),
        metadata.get("scope"),
    )
    base = {
        "semantic": supplied.get("semantic") or _join_nonempty(semantic_prefix, summary, text),
        "keywords": supplied.get("keywords") or supplied.get("topic_keywords") or supplied.get("free_keywords") or keyword_text,
        "workspace": supplied.get("workspace") or workspace,
    }
    selected = set(KIND_DEFAULT_FACETS.get(type_, ("semantic", "keywords")))
    selected.update(name for name in supplied if name in DEFAULT_MEMORY_FACETS)
    selected.add("semantic")
    selected.add("keywords")
    if any(metadata.get(key) for key in ("workspace", "cwd", "project_root", "path", "module")) or supplied.get("workspace"):
        selected.add("workspace")

    result: dict[str, str] = {}
    for name in DEFAULT_MEMORY_FACETS:
        if name not in selected:
            continue
        value = str(base.get(name) or "").strip()
        if value:
            result[name] = value[:1200]
    return result


def _keyword_text(facets: dict[str, str], summary: str, text: str) -> str:
    explicit = facets.get("keywords") or facets.get("topic_keywords") or facets.get("free_keywords")
    if explicit:
        return str(explicit).strip()[:1200]
    keywords = extract_keywords(" ".join([summary, text]), max_keywords=32)
    return ", ".join(keywords)


def extract_keywords(text: str, max_keywords: int = 32) -> list[str]:
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
    if any(token in q for token in ("today", "recent", "latest", "last time", "just now", "最新", "现在", "进度")):
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
