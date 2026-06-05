# Runtime Model

## Goal

The first implementation favors maintainability and replaceable backends. The runtime should be a small deterministic supervisor plus isolated agent processes/workers.

## Runtime priority

Control priority is fixed:

```text
audit-agent > main-agent > user interrupt > interactive-agent
```

The supervisor is still the only component that executes process-control commands.

## Process roles

```text
advanced-agentd / Supervisor
├── interactive-agent   provisional quick feedback and stream rendering
├── main-agent          authoritative semantic decision maker
├── audit-agent         independent review and veto layer
├── memory-worker       memory alignment, vector labels, lifecycle
└── codex-task-worker   heavy task backend wrapping Codex CLI
```

## Stop semantics

Agents should use graceful management methods:

- `pause`
- `resume`
- `stop`
- `cancel`
- `snapshot`

`terminate` and `kill` are supervisor-internal fallback mechanisms. Normal agents should not receive raw OS process ownership.

## Interactive vs main

Interactive output is provisional. Main output is authoritative. A later authoritative stream item can supersede previous provisional stream items by request id and sequence/version.

## Non-blocking operation

The supervisor must not block on long-running agents. Task agents are spawned asynchronously in later versions. The first skeleton keeps APIs synchronous where simple but stores state in a way compatible with async subprocess management.
