# Memory Design

## 1. Goal

Advanced Agent memory is a unified vector-backed control plane, not a split
"event DB vs memory DB" semantic world.  Raw events, dialogue, task output, and
curated memories are different views of local runtime history; durable retrieval
should be controlled by structured metadata plus multi-dimensional vector facets.

The target model is:

```text
raw input/event/message/task output
  -> bounded raw stores for audit and tail inspection
  -> MemoryCandidate / ingest classifier
  -> unified MemoryRecord metadata
  -> multiple facet vectors
  -> query-profile based retrieval and prompt injection
```

## 2. Storage roles

- `messages`, `interaction_streams`, `runtime_events`, `task_events`,
  `task_output_chunks`: raw/runtime history. They are complete enough for audit
  and bounded tail reads, but are not all injected into prompts.
- `memory_items`: unified durable memory records. Stores scope, type/kind,
  summary/content, confidence, importance, lifecycle, and source reference.
- `memory_vectors`: facet vector mapping. One memory record can have many facet
  vectors.
- `vec_memory`: current sqlite-vec adapter table. It is a replaceable backend;
  the higher-level design intentionally matches named-vector databases such as
  Qdrant.

## 3. Memory kinds

Common `memory_items.type` values:

- `decision`: confirmed design choice or constraint.
- `user_preference` / `preference`: user habit or collaboration style.
- `project_state`: current project status, module state, or progress.
- `session_summary`: compacted dialogue summary.
- `procedure`: reusable workflow.
- `warning`: risk, pitfall, or negative constraint.
- `handoff`: continuation note / next-step state.
- `chat`: low-stakes conversational background.
- `codex_interactive_log`: noisy terminal/transcript-derived record, excluded
  from normal `context_get` unless requested.

Kinds are not separate databases. They are metadata used for filtering,
weighting, and lifecycle control.

## 4. Facet control plane

Each memory can generate several facet texts. Current first-class facets:

- `semantic`: general content meaning.
- `project`: project/path/scope relevance.
- `time`: recency, phase, continuation, temporal wording.
- `methodology`: design habit, architectural principle, collaboration method.
- `project_feature`: module, feature, subsystem, project-specific property.
- `implementation`: code/tool/config detail.
- `decision`: confirmed choice or constraint.
- `preference`: user preference.
- `procedure`: reusable workflow.
- `risk`: warning/failure mode.
- `handoff`: progress and next-step context.
- `chat`: informal conversation/background.
- `agent_relevance`: why a future agent should care.

`MemoryIndexer` now normalizes classifier/LLM/fallback output into this facet
set. sqlite-vec stores one vector row per facet; a future Qdrant adapter can map
these to named vectors or separate vector names without changing the logical
record model.

## 5. Query profiles

Retrieval should not always search all vectors equally. `memory.search` and
`context_get` accept a `query_profile` plus optional facet weight overrides.
Supported profiles include:

- `auto`: infer from query text.
- `general`
- `design`
- `project`
- `methodology`
- `preference`
- `procedure`
- `risk`
- `handoff`
- `chat`
- `recent`

Example:

```text
query_profile=design
  decision > project > methodology > project_feature > semantic

query_profile=methodology
  methodology > preference > procedure > semantic
```

The current sqlite-vec adapter implements this as overfetch + facet-weighted
reranking. A stronger backend can perform the same profile logic with named
vectors/hybrid search.

## 6. Raw tail / ring-buffer policy

Raw dialogue is kept in SQLite history, but the model should not receive the
whole raw stream by default. Instead it can explicitly call:

```text
session.raw_tail / session_raw_tail
```

This returns a bounded, ring-buffer-like recent raw window with `limit` and
`max_chars`. It is for overflow inspection and local continuity, not durable
semantic memory. Main prompts now tell the model to call raw tail tools when it
needs more recent raw rows instead of asking the user to restate.

## 7. Ingest policy

入库分类应发生在 memory ingress 阶段：

```text
MemoryCandidate
  -> kind/type
  -> facets
  -> metadata/tags/source_ref
  -> dedup
  -> memory_items + memory_vectors
```

Raw events may be promoted into memory, but should not be injected merely
because they exist. The distinction is not two databases; it is metadata,
facets, importance, and query-time control.
