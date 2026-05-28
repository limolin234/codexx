# Architecture Review - 2026-05-28

## Verdict

The current core split is sound enough to freeze as the baseline:

```text
supervisor / main / interactive / audit / task / memory / plugin
```

The main risks are not the role split, but missing contracts around decision persistence, migrations, context assembly, background loops, and replacement boundaries.

## What is good

### 1. Role separation is clear

- Supervisor owns deterministic runtime and process control.
- Main owns semantic authority.
- Interactive owns user-facing voice and fast feedback.
- Audit owns high-priority safety review.
- Task/Codex worker owns bounded execution.
- Memory/preference workers own long-term adaptation.
- Plugins own external integrations.

This avoids making main-agent a god object.

### 2. User-facing channel is coherent

The user talks to interactive. Main output is rendered through interactive. This keeps voice consistent and preserves main as internal semantic authority.

### 3. Storage split is reasonable

- SQLite for structured state and metadata.
- sqlite-vec for local vector retrieval.
- filesystem for large artifacts.
- event log for runtime observability.

This fits edge devices better than a heavier service database.

### 4. Hooks are now core infrastructure

Hook-driven automation is the right direction. Manual memory/profile/index maintenance is not scalable.

### 5. Codex is correctly isolated

Codex is a task backend, not the runtime. This preserves replaceability.

## Issues to fix before replacing placeholders

### Issue 1: Main decisions need durable first-class storage

Current main decisions are indirectly represented by stream rendering and events. That is not enough for audit, replay, or correction.

Need a `main_decisions` table/store containing:

- request_id;
- session_id;
- intent;
- decision_type;
- internal_summary;
- user_visible_instruction;
- task requests;
- audit status;
- created_at.

Interactive should render from a stored main decision, not from an ephemeral return value.

### Issue 2: Schema migration story is still weak

`CREATE TABLE IF NOT EXISTS` is fine for early prototyping, but long-lived local software needs migrations.

Need:

- schema version table;
- ordered migrations;
- idempotent upgrade;
- doctor check for DB version.

### Issue 3: ContextBuilder is not yet the only prompt assembly path

Agents still construct prompts directly in their own files. Long term this will cause prompt drift.

Need:

- `ContextBuilder` as the only prompt input assembler;
- role-specific context builders;
- prompt overlays injected centrally;
- memory retrieval injected centrally.

### Issue 4: Automation lacks a real runtime loop

`AutomationEngine.tick()` exists but is not running in a service loop.

Need:

- async runtime loop;
- tick interval;
- graceful shutdown;
- event-driven wakeups later.

### Issue 5: Memory indexing is still only manual/partial

Compaction writes session summaries to vector memory, and `/mem` exists, but there is no unified `MemoryIndexer` pipeline.

Need:

- memory candidates;
- dedup;
- alignment;
- vector label write;
- reindex;
- source tracking.

### Issue 6: Plugin hook dispatch is event-only

This is acceptable for now, but eventually plugin agents need a registry/runner.

Need later:

- plugin worker spec;
- plugin permissions;
- plugin-specific data directories;
- plugin event consumption contract.

## Suggested next order

Do not replace model/embedding placeholders yet. First fix structural contracts:

1. MainDecisionStore and main decision table.
2. Central ContextBuilder prompt assembly path.
3. Persistent migration/version mechanism.
4. MemoryIndexer pipeline.
5. Background automation runtime loop.
6. Then replace placeholders:
   - real embedding model;
   - real memory alignment model;
   - streaming LLM client;
   - real audit model.

## Architecture freeze statement

Keep the current role split. Do not merge:

- main with interactive;
- supervisor with main;
- Codex worker with supervisor;
- memory/preference worker with main;
- plugin logic with core.

Future work should strengthen contracts, not add cross-module shortcuts.
