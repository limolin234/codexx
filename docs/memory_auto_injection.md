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
- MCP `context_get` defaults to `mode="supplement"` for external Codex-style
  agents: it skips the live recent tail that Codex likely already sees and
  returns only older supplemental session lines plus vector memory hits. Use
  `mode="full"` when a caller explicitly needs the complete bounded view.

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

- `memory.search` and `context_get` accept `query_profile` and optional facet
  weight overrides. The sqlite-vec adapter overfetches and reranks by facet
  weight; the logical interface is compatible with a future named-vector backend.
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
