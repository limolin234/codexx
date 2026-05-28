# Advanced Agent Architecture V1

This document is the first architecture baseline. Implementation should follow these contracts instead of adding ad-hoc shortcuts.

## 1. Design goal

Build a long-lived local agent system for efficient interaction and computer management. The system should be maintainable, modular, and suitable for later migration to edge devices with limited memory.

Primary values:

- clear module ownership;
- replaceable backends;
- low-latency interaction;
- strong semantic control;
- auditable process and tool management;
- vector-first long-term memory;
- graceful stop before destructive kill.

## 2. Core roles

### Supervisor

The supervisor is deterministic runtime infrastructure, not an LLM.

Responsibilities:

- process lifecycle;
- task registry;
- SQLite state;
- control command execution;
- interrupt gate;
- time service;
- hook scheduler;
- task output collection;
- audit enforcement.

Non-responsibilities:

- semantic reasoning;
- user-facing wording;
- long-term memory judgment;
- direct model creativity.

### Main agent

The main agent is the semantic authority.

Responsibilities:

- intent judgment;
- task planning;
- deciding whether to spawn task workers;
- deciding whether interactive output must be corrected;
- reading task state/history/tail when needed;
- requesting memory search;
- requesting hooks;
- deciding whether the user should be notified.

The user does not directly converse with main agent. Main agent produces internal authoritative content. Interactive agent renders it for the user.

### Interactive agent

Interactive agent is the user-facing shell.

Responsibilities:

- quick acknowledgement;
- stream rendering;
- consistent user-facing voice;
- receiving user interrupts;
- replaying main agent decisions in a stable style;
- not doing deep semantic judgment.

Interactive output is provisional unless it is rendering main-authoritative content.

### Audit agent

Audit agent is independent review authority.

Priority:

```text
audit > main > user interrupt > interactive
```

Responsibilities:

- reviewing dangerous actions;
- vetoing unsafe main decisions;
- stopping task execution when risk is detected;
- checking memory writes when needed;
- escalating to supervisor.

### Task agent / Codex worker

Task agents perform bounded work. Codex CLI can be used as the first heavy task backend.

Responsibilities:

- code/file/tool-heavy tasks;
- returning progress/final reports;
- not owning global state;
- not talking directly to the user.

## 3. User-facing flow

```text
user input
  -> interactive quick provisional reply
  -> main internal semantic decision
  -> audit review if needed
  -> supervisor action if needed
  -> interactive renders main result to user
```

The user-facing channel should be consistent. Main agent should not speak directly to the user in normal operation.

## 4. Context model

Contexts are separated by ownership.

### Shared visible context

Read by main and interactive:

- latest user message;
- current request id;
- interactive stream offsets;
- main visible state;
- active task summaries;
- pending interrupts.

### Main private context

Owned by main:

- semantic interpretation;
- planning state;
- retrieved memories;
- task management decisions;
- audit requests.

### Interactive private context

Owned by interactive:

- UI stream state;
- quick reply state;
- rendering style;
- last user-visible output.

### Task context

Owned by task agent/worker:

- task-local files;
- tool results;
- local scratch;
- checkpoint/final report.

### Memory context

Owned by memory subsystem:

- memory items;
- vector labels;
- vector ids;
- source metadata;
- lifecycle.

## 5. Storage model

SQLite is structured state and metadata. It is not the semantic search engine.

SQLite stores:

- sessions;
- messages;
- streams;
- tasks;
- task states;
- task outputs;
- audit reviews;
- control commands;
- memory metadata;
- vector id mappings.

Vector DB stores:

- retrieval vectors;
- label-kind-specific memory vectors;
- top-k semantic retrieval support.

Large artifacts stay in the filesystem.

## 6. Memory model

Long-term memory is vector-first.

```text
query -> vector search -> memory ids -> SQLite hydration
```

Memory quality should come from a memory-alignment agent generating good labels, not from brute-force scanning.

A memory item may have multiple vector labels:

- semantic;
- task_intent;
- decision;
- user_preference;
- project_context;
- warning;
- procedure;
- agent_relevance.

## 7. Hook and time model

The runtime owns time.

Agents may request hooks, but models do not own real timers.

Hook semantics:

- hooks usually wake main agent;
- waking main does not imply speaking to the user;
- main decides whether interactive should notify the user;
- idle sessions back off to longer sleep intervals.

Two time sources are required:

- wall time for user-facing dates;
- monotonic time for timeout, heartbeat, cooldown, and elapsed duration.

## 8. Control and safety model

Normal public controls:

- pause;
- resume;
- stop;
- cancel;
- snapshot.

Supervisor-internal fallback:

- terminate;
- kill.

`kill` should not be a normal agent-level method.

Interrupts pass through interrupt gate:

- enable/disable flags;
- cooldown;
- priority;
- emergency bypass only for explicit high-risk stop cases.

## 9. Model configuration

Model configuration is local JSON:

```text
.env.json
```

Roles:

- interactive_model;
- main_model;
- audit_model;
- codex_model.

`codex_model = default` means Codex CLI uses its own default configuration.

## 10. Current implementation status

Implemented skeleton:

- RuntimeApp;
- SQLite schema;
- stores;
- supervisor;
- interrupt gate;
- audit mock;
- interactive/main mock;
- sqlite-vec adapter;
- JSON model config;
- simple CLI.

Not yet complete:

- true token streaming;
- CodexTaskWorker;
- async subprocess task execution;
- LLM audit;
- real memory alignment agent;
- real embedding model;
- hook persistence and runtime loop;
- conversation compaction/cleanup.

## 11. Architecture rule

When adding a feature, first decide:

1. Which module owns it?
2. Which context does it read/write?
3. Is it user-facing or internal?
4. Does it require audit?
5. Does it belong in SQLite, vector DB, or filesystem?
6. Can the backend be replaced later?

If the answer is unclear, do not implement yet.
