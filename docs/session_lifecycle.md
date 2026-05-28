# Session Lifecycle and Context Rollback

The default interaction model is a single persistent conversation. Opening the
CLI/runtime resumes the default active session instead of creating a fresh
conversation every time.

Long-term recall should come from vector memory and summaries, not from keeping
all raw conversation text in the prompt. The raw history remains in SQLite for
audit/debugging, while prompt context can be cleared by time.

## Operations

- `default_session(title="default")`: resume the active default session, or create
  it if missing.
- `clear_context_before_ms(session_id, cutoff_ms)`: mark messages at/before a
  wall-clock timestamp as compacted, so they no longer enter normal context.
- `rollback_context_to_ms(session_id, cutoff_ms)`: mark messages after a
  wall-clock timestamp as compacted. This behaves like a context rollback but
  does not delete history.
- `context_stats(session_id)`: inspect active/compacted message counts and
  active context size.

## CLI

```text
/context
/clear-before <wall_ms>
/rollback-to <wall_ms>
```

Use `--new-session` only when a separate fresh conversation is explicitly needed.
