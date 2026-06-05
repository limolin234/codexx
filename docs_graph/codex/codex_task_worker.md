# Codex Task Worker

Codex is used as a replaceable heavy task backend, not as the system runtime.

## Boundary

CodexTaskWorker owns:

- `codex exec --json` command construction;
- stdout/stderr collection via AsyncSubprocessRunner;
- Codex JSONL parsing;
- writing task output and task events.

It does not own:

- user-facing interaction;
- main-agent semantic decisions;
- global memory;
- process priority policy;
- audit priority.

## Data flow

```text
Codex subprocess stdout/stderr
  -> AsyncSubprocessRunner tail
  -> CodexTaskWorker output callback
  -> task_output_chunks
  -> task_events
  -> summaries later
```

Upper agents inspect progress by reading task state, tail, and events from supervisor/stores.
