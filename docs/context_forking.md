# Context Forking

Some work should be delegated to a task/sub-agent with a bounded copy of the
current context, not by letting the main loop carry all details forever.

A context fork is not a process fork. It is a stable, bounded prompt/resource
bundle:

```text
parent session + request + goal
  -> recent user-visible context
  -> retrieved vector memories
  -> role/focus/constraints
  -> stable cache key
  -> task/sub-agent prompt
```

Goals:

- keep sub-agent instruction following tight;
- align sub-agent task with parent goal;
- avoid bloating main context;
- improve provider prompt-cache hit rate by keeping stable source/context blocks;
- preserve an auditable link to parent session/request.

First implementation:

- `ContextForkSpec`
- `ContextFork`
- `ContextForkBuilder`

Later this should be wired into `spawn_task` / CodexTaskWorker so heavy tasks get
clean forked context instead of ad-hoc raw user text.
