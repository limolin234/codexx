# Wrapper automatic memory and profile maintenance

`codexx` should keep the interrupt/exit path fast. Ctrl+C, SIGTERM, normal
close, and crash recovery only append small lifecycle events, flush a bounded
raw tail, enqueue background memory/profile jobs, and return. They must not call
models, build embeddings, or wait for summaries.

## Model routing

Wrapper-side automation uses layered routing:

1. **L0 event router**: no keyword-based semantic extraction. It only records
   event source (`user`, `assistant`, `tool`, `wrapper`), event kind, cwd/session
   metadata, and safety filters such as secret/binary/noisy terminal guards.
2. **L1 cheap observer**: watches recent user-originated evidence and verified
   tool outcomes, emits untrusted candidate patches only. It never commits
   long-term user traits.
3. **L2 strong memory writer**: approves all durable profile-memory writes,
   profile diffs, conflict resolution, and periodic consolidation through an
   explicit tool/function-call interface.
4. **Codex itself**: still actively calls `context_get` and `memory_write` for
   semantically important task work. Wrapper injection remains restrained and
   does not replace tool use. Low-level search/recent operations are routed
   internally by `context_get`.

User profile is stored as ordinary vector memory records such as `user_trait`,
`preference`, and `workflow_habit`. The wrapper owns lightweight profile
indexing and restrained injection; Codex should mainly write project-specific
progress, decisions, validations, and handoffs while doing the work.

`user_profiles.summary` and `prompt_overlays:user_profile` are only compact
startup hints for internal prompt builders. They are not the authoritative
profile. Codex-facing runtime calls receive profile through a separate
`profile_hints` capsule in `context_get`, selected by `ProfileHintSelector`
from high-confidence vector profile records without waiting on a model. The
selector performs local vector/FTS retrieval plus policy filtering, scope
fallback, raw-evidence suppression, and injection dedupe at the caller boundary.
Complex profile state remains searchable through the vector memory store, but
ordinary task memories do not include profile records by default.

Durable profile updates are diff-based and authoritative writes are owned by a
strong model. The cheap `memory_model` is only an observer: it may propose
add/update/supersede/remove candidates, but those candidates are treated as
untrusted hints because small models hallucinate. Real vector-memory writes for
profile maintenance require the `memory_write_model` role, falling back to
`main_model`, and the model must approve changes through a function/tool-call
interface. If no strong writer model is configured, wrapper profile maintenance
updates the lightweight overlay/checkpoint only and does not create distilled
traits.

## Evidence and positive feedback control

User traits must be grounded in evidence. Assistant output must not become user
profile evidence, because that creates self-reinforcing prompt pollution.

Preferred `source_strength` values:

- `explicit_user`
- `user_correction`
- `user_behavior`
- `tool_verified`
- `model_summary`
- `wrapper_inference`
- `assistant_output` (never injectable as a user trait)

Wrapper-inferred traits may be stored as candidates, but prompt injection should
require high confidence and user/tool-grounded evidence.

## Injection budget

Injection should be minimal:

- internal compact profile overlay from high-confidence vector traits: about 800 chars
- Codex-facing `profile_hints`: at most 3 short hints, deduped per caller session
- ordinary query-routed memories: summary-only compact view by default

The request-time selector must not call an LLM. Expensive profile maintenance is
asynchronous; prompt-time injection is a cheap read from already indexed profile
memory.

Everything else should remain searchable through memory tools.

## Maintenance frequency

User requests schedule background maintenance hooks, but profile distillation is
throttled. The worker records an internal checkpoint and reruns profile
maintenance only when there is no prior checkpoint, at least four new user
messages arrived, or at least ten minutes passed and there is new evidence. This
keeps the interrupt path fast and avoids calling memory models on every turn.

## Lifecycle and cleanup

Long-term records live in `memory_items` with lifecycle metadata:

- `importance`, `confidence`
- `source_strength`, `stability`
- `usage_count`, `last_used_at_ms`, `last_evidence_at_ms`
- `supersedes_id`, `superseded_by`
- `status`: `active`, `inactive`, `superseded`, `archived`, `deleted`

Default retrieval only sees `active`. Cleanup is staged:

1. mark inactive/superseded/deleted as soft lifecycle changes;
2. archive inactive indexes by deleting vector/FTS/facet rows while keeping the
   memory item tombstone;
3. physically purge old `deleted` tombstones later and run SQLite maintenance in
   a low-priority background job.

Raw session logs should be treated as short-retention buffers: summarize first,
then prune. Durable vector memory should store summaries, decisions, traits,
project states, handoffs, and verifications rather than raw terminal logs.

## Model-facing tool budget

The MCP server should expose only tools that help Codex reason or act during the
current task. Internal maintenance such as archiving inactive indexes and purging
deleted tombstones stays in `RuntimeToolBridge`/automation hooks and is not added
to the model-facing MCP tool list. This keeps the tool schema smaller and avoids
spending model attention on lifecycle plumbing.

Codex-facing memory tools are therefore:

- `context_get` for context lookup, semantic memory search, and recent-memory recaps
- `memory_write` for durable decisions, preferences, progress, and handoffs
- `session_raw_tail` only when raw overflow dialogue must be inspected

Background lifecycle work is triggered by `memory_maintenance` / `raw_retention`
hooks and daemon ticks, not by the model choosing cleanup tools. Codex should use
its own built-in cwd/task mechanisms; Advanced Agent workdir/task/timer/event
runtime tools remain internal unless deliberately re-exposed later.
