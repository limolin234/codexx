# Tool Resource Model

Tools are runtime resources/capabilities, not hardcoded prompt assumptions.

## Principle

The supervisor owns tool/resource allocation. Agents receive capability views.

```text
ToolRegistry / ResourceManager
  -> capability view for main / interactive / task / plugin
  -> audit/permission checks
  -> execution backend
```

## Main agent tools

Main agent should have basic controlled tools for system reasoning and management:

- read task state/history/tail;
- search memory;
- schedule hooks;
- request task creation;
- request stop/cancel;
- request audit;
- inspect available capabilities.

Main agent should not directly own raw shell or destructive OS tools.

## Interactive agent tools

Interactive agent should have minimal read-only tools:

- current task summaries;
- stream state;
- user interrupt submission;
- main visible state.

It should not execute tools directly.

## Task/Codex tools

Heavy execution belongs to task agents, especially CodexTaskWorker for code/file/shell-heavy work.

Codex available tools are determined by:

- Codex CLI config;
- sandbox mode;
- approval mode;
- workdir/additional dirs;
- audit policy;
- runtime permission policy.

The core should maintain a Codex backend capability record so main can know what kind of task can be delegated without assuming exact low-level tools.

## Future interfaces

Needed later:

- `ToolRegistry`
- `CapabilityView`
- `ToolRequest`
- `ToolResult`
- `ResourcePolicy`
- `CodexCapabilityProbe`

This should be implemented before exposing real tool calls to main models.
