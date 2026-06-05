# Context Interface

Agents should not receive raw database connections, raw OS process control, or raw tool ownership. They receive narrow context interfaces.

## Contexts

- `TimeContext`: wall and monotonic time.
- `SessionContext`: messages and stream deltas.
- `SharedStateContext`: visible shared state between interactive and main.
- `SignalContext`: local pause/cancel/heartbeat state for an agent.
- `TaskContext`: task lifecycle operations through supervisor.
- `AuditContext`: request review and record audit decisions.
- `MemoryContext`: vector-first memory search/proposal in later versions.
- `ToolContext`: permissioned tool request in later versions.

## Access principle

Each module owns a data access interface. SQLite is an implementation detail behind stores such as `SessionStore`, `TaskStore`, and `AuditStore`.
