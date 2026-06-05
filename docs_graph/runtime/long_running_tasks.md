# Long-running tasks

Long-running work should not keep a model call alive. The first-version pattern is:

```text
codexx / MCP tool
  -> schedule hook or create managed task
  -> advanced-agentd ticks deterministic runtime
  -> worker/plugin reads external state
  -> summaries/memory are written to SQLite + sqlite-vec
  -> Codex/main later uses context_get/memory_search/task_tail
```

## Run the runtime daemon

Start the deterministic runtime loop in another terminal:

```bash
advanced-agentd
```

It auto-enters the project virtualenv and uses the default `.env.json` and
`runtime/advanced_agent.sqlite`.

One-shot tick for debugging:

```bash
advanced-agentd --once
```

Useful environment overrides:

```bash
ADVANCED_AGENT_DB=runtime/advanced_agent.sqlite \
ADVANCED_AGENT_CONFIG=.env.json \
ADVANCED_AGENT_DAEMON_TICK=1.0 \
advanced-agentd
```

## What the daemon currently runs

`advanced-agentd` calls `AutomationEngine.tick()` repeatedly. Current hook kinds:

- `preference_maintenance`: derive/update user preference prompt overlays.
- `compact_memory`: replace over-budget live context with vector-indexed session summary.
- `memory_index`: write supplied text into the memory pipeline.
- `check_tasks`: summarize active managed tasks.
- `wake` / `check_state`: deterministic wake signals for future main-agent checks.
- `plugin.*`: publish plugin hook requests for external connectors.

## How to schedule from Codex/MCP

Codex should use MCP tools instead of sleeping:

- `timer_schedule(delay_ms, reason, target, payload_json)` schedules a wake hook.
- `event_wait(type, timeout_ms)` only waits briefly; long waits should become hooks.
- `memory_write(...)` records durable state.
- `task_tail/task_state/task_list` inspect managed tasks without interrupting them.

## Example: periodic group watcher later

A connector/plugin should run as a worker or plugin hook, not as a forever model
call:

```text
plugin.group_chat.poll every N seconds
  -> read new messages by offset
  -> batch summarize
  -> memory_write important summary/preferences
  -> publish event if user attention is needed
```

The model wakes only when needed to judge or respond.
