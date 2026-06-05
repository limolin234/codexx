# Subprocess Runtime

The system is intended to be a host-level management AI. It should run on the host rather than inside Docker by default. Docker can be revisited for optional task isolation, but the core service must manage the host system.

## Requirements

Subprocess infrastructure must support:

- non-blocking execution;
- live stdout/stderr tail;
- graceful stop first;
- kill only as fallback;
- output callbacks for task stores/event logs;
- no disturbance to the running task when upper agents inspect progress.

## Tail access

Upper agents should inspect task progress by reading supervisor-managed tail buffers and summaries, not by asking task agents to stop and report.

```text
subprocess stdout/stderr
  -> tail ring buffer
  -> task_output_chunks
  -> summarizer
  -> main/interactive read-only progress view
```

## Tool calls

For Codex, tool calls will appear as JSONL events or text output. The subprocess runner only captures raw streams. A CodexTaskWorker parser should later classify:

- assistant text;
- tool call request;
- tool call output;
- final message;
- usage;
- errors.
