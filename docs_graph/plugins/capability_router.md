# Capability Router

The core should not expose every low-level tool or Codex skill to main-agent. Main sees abstract capabilities with backend, latency, risk, and audit requirements.

## Core idea

```text
Main intent
  -> CapabilityRouter
  -> core low-latency management capability
  OR codex-cli heavy task backend
  OR plugin hook
```

## Current default capabilities

- `task_state`: core, low latency, low risk.
- `memory_search`: core, low latency, low risk.
- `hook_schedule`: core, low latency, low risk.
- `interrupt_request`: core, low latency, medium risk.
- `code_editing`: codex-cli, high latency, medium risk, task + audit.
- `project_analysis`: codex-cli, high latency, medium risk, task + audit.
- `document_generation`: codex-cli, high latency, low risk, task.
- `plugin_hook`: plugin, medium latency, medium risk, audit.

## Prompt integration

PromptBuilder includes the abstract capability list for main-agent. It does not include every underlying Codex tool or skill.
