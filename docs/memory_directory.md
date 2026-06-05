# Memory directory contract

`memory/` is the user-migratable asset directory. Future releases should keep
this layout compatible and migrate schemas in place on startup.

```text
memory/
  longterm.sqlite   # durable vector memory and compact profile records
  rawtail.sqlite    # cleaned bounded raw-tail cache, target ~10 MiB
runtime/
  advanced_agent.sqlite  # tasks, hooks, sessions, semantic worker state
```

Boundaries:

- `longterm.sqlite` owns `memory_items`, `memory_vectors`, `memory_facets`,
  `memory_fts`, and `user_profiles`.
- `rawtail.sqlite` owns `rawtail_chunks`. It is recent evidence only, not
  authoritative long-term memory.
- `runtime/advanced_agent.sqlite` owns task state, hooks, sessions, prompt
  overlays, semantic cleaning/compression tasks, events, and injection ledger.

Operational behavior:

- Ctrl-C should flush the cleaned codex tail into `rawtail.sqlite`, schedule
  runtime maintenance, stop background workers, and close all SQLite handles.
- SIGKILL may lose short-term runtime/rawtail chunks, but the next startup must
  initialize all three databases and continue normally.
- Device migration may copy only `memory/`; losing `runtime/` is acceptable.
