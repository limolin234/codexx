# Memory auto-injection and replacement

First-version memory loop:

```text
user/session/task content
  -> MemoryService.write / ConversationCompactor
  -> MemoryIndexer
  -> LLMMemoryAlignment labels, with deterministic fallback
  -> SQLite metadata + sqlite-vec vectors
  -> ContextBuilder/context_get hydrates and injects relevant memory content
```

## Automatic injection

- `ContextBuilder.build_for_main()` now retrieves hydrated `MemoryRecord`s via
  `MemoryService`, not just vector IDs/summaries.
- `PromptBuilder.main_decision()` injects both summary and bounded memory content
  into the main-agent prompt.
- MCP `context_get` defaults to `mode="supplement"` and `view="compact"` for
  external Codex-style agents. Compact results return `context_lines`,
  `profile_hints`, and summary-only `memories`; debug fields such as scores,
  labels, excluded types, and duplicate-skip details are returned only with
  `view="debug"`. Use `mode="full"` when a caller explicitly needs the complete
  bounded view. These are the only valid modes; callers must not send legacy
  values such as `brief`.
- Runtime injection dedupe is handled inside the wrapper by
  `session_injection_ledger`. The ledger records stable ids for items actually
  returned by `context_get` (`memory_id`, profile key, context line id), then
  suppresses repeat injection in the same caller session. This is an injection
  hygiene mechanism, not semantic memory deduplication.
- `profile_hints` are a separate compact capsule selected deterministically from
  active high-confidence `user_trait` / `preference` / `workflow_habit` records.
  `context_get` does not block on memory/profile models to generate them; model
  maintenance updates profile records asynchronously for later calls. Profile
  records are excluded from ordinary `memories` by default so user traits do not
  randomly pollute task-memory retrieval.

## Replacement / compaction

- `AutomationEngine.ensure_session_maintenance()` schedules both preference
  maintenance and `COMPACT_MEMORY` hooks.
- `context_get` performs a safe `compactor.maybe_compact()` before retrieving
  context, so over-budget dialogue can be replaced by vector-indexed summary
  memory.
- `SessionStore.session_context_lines()` hides authoritative assistant stream
  lines whose request has been compacted, so compacted turns are actually removed
  from live context rather than duplicated.
- In supplement mode, memory content is summary-only by default to avoid dumping
  raw terminal logs or duplicate live context into Codex. Callers can opt in with
  `include_memory_content=true`.

## Facet generation

- `LLMMemoryAlignment` is the primary facet generator when `memory_model` is
  configured.
- Rule-based `MemoryAlignment` remains the fallback.
- `MemoryIndexer` normalizes all facet output through `memory_facets.py`.
- Stored facet/label kinds now include:
  - `semantic`
  - `project`
  - `time`
  - `methodology`
  - `project_feature`
  - `implementation`
  - `decision`
  - `preference`
  - `procedure`
  - `risk`
  - `handoff`
  - `chat`
  - `agent_relevance`
- Schema v2 stores `memory_vectors.label_text`, so tool callers can inspect which
  facet texts were generated, not only vector hashes.

## Query profiles and raw tail

- Internal `memory.search` and model-facing `context_get` accept `query_profile`
  and optional facet weight overrides. The sqlite-vec adapter overfetches and
  reranks by facet weight; the logical interface is compatible with a future
  named-vector backend.
- Recent-memory retrieval is chronological, not semantic: internally it returns
  active durable records ordered by `updated_at_ms DESC, created_at_ms DESC,
  rowid DESC`. Codex gets this through `context_get` with an empty/vague query.
  Callers should not add manual sorting for ordinary "recent activity" recaps.
- `session.raw_tail` / `session_raw_tail` exposes a bounded raw dialogue tail for
  overflow inspection. It behaves like a ring-buffer view over raw session rows:
  callers choose `limit` and `max_chars`, and the model can call it when recent
  context is insufficient.

## Vector database

The first version uses `sqlite-vec`:

- `memory_items`: source, summary, content, lifecycle metadata.
- `memory_vectors`: one vector per generated label, including `label_kind` and
  `label_text`.
- `vec_memory`: sqlite-vec virtual table for nearest-neighbor search.

This keeps the edge-device path simple while preserving a clean adapter boundary
for future embedding/vector backend replacement.

## Keyword-first label contract

`LLMMemoryAlignment` should now behave as a vector-memory keyword labeler, not a
large ontology classifier.  It should output compact JSON with these preferred
keys:

```json
{
  "semantic": "short factual retrieval text",
  "keywords": "high-value future search terms and phrases",
  "workspace": "optional concrete paths/modules/projects"
}
```

Unsupported dimensions should be omitted.  Time is maintained by the runtime;
the labeler should not invent timestamps.  Passive observation is not a hot-memory
signal.
