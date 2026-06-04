# Cleaned TTY semantic runtime

`codexx` keeps the wrapper source generic enough for Codex, Claude, and other
terminal agents by treating the TTY stream as the primary input instead of
depending on a vendor-specific transcript format.

Pipeline:

1. Clean terminal output with ANSI/OSC stripping, carriage-return overwrite
   normalization, duplicate-line collapse, and bounded terminal logs.
2. Track best-effort user submissions from raw TTY input.
3. Persist compact semantic events (`user_submit`, `cleaned_tty_chunk`,
   `session_close`) into SQLite while also keeping a 1 MiB in-memory ring.
4. Schedule semantic maintenance after three user submissions, buffer pressure,
   or session close/interrupt.
5. Compress older semantic events into `semantic_summaries`; mark source events
   compacted in the same transaction.
6. Create conservative memory candidates from summaries. Durable vector-memory
   writes require the configured `memory_write_model` approval tool call; if no
   approval model is configured, candidates remain non-durable.

Crash behavior:

- Ctrl-C/SIGTERM paths append close/interruption state and schedule immediate
  semantic maintenance.
- `semantic_tasks` and `semantic_memory_candidates` are persisted with explicit
  statuses. Stale `running` tasks are recovered on the next maintenance run.
- `kill -9` cannot run exit handlers, but events already committed to SQLite
  are recoverable and task/memory writes are idempotent by hash/source id.

The semantic summaries are runtime compression state, not authoritative long-term
memory. Long-term memory should stay conservative because bad durable memories
are more expensive to clean up than occasional model calls.
