# codexx runtime architecture

这份图用于说明 `codexx` 对 Codex/终端 agent 的侵入边界、外部资源使用、
任务队列、SQLite 数据库、日志文件、模型 API 调用，以及内部处理流程。

## 1. 外部接入与侵入边界

```mermaid
flowchart LR
  U[User terminal] -->|TTY input/output| W[codexx wrapper]
  W -->|spawn PTY child| C[Codex CLI / other TTY agent]
  C -->|normal CLI behavior| OA[OpenAI/Codex API]

  W -->|temporary -c config only| MCP[Advanced Agent MCP server]
  C -->|MCP tool calls| MCP
  MCP --> DB[(runtime/advanced_agent.sqlite)]

  W -->|cleaned bounded log| FS[runtime/codex_interactive/*.terminal.log]
  W -->|combined model instructions file| INST[runtime/codex_interactive/*.instructions.md]
  W -->|semantic events / hooks| DB

  BG[BackgroundRuntimeQueue] -->|due hooks| DB
  BG -->|memory_model / memory_write_model| LLM[External OpenAI-compatible model APIs]
```

侵入方式：

- 不修改 Codex 全局配置。
- 启动时通过临时 `-c` 注入：
  - project-local MCP server
  - temporary `model_instructions_file`
- Codex 仍然使用自己的模型/API；`codexx` 只包一层 PTY、MCP 和 runtime。
- 对 Claude 或其他 TTY agent，主路径仍然是通用 TTY 清洗，不依赖 Codex 专有 transcript。

## 2. 磁盘资源分类

```mermaid
flowchart TB
  subgraph Files[Filesystem]
    LOGS[runtime/codex_interactive/*.terminal.log<br/>cleaned, max 5 MiB each]
    INSTR[runtime/codex_interactive/*.instructions.md<br/>small generated instruction files]
  end

  subgraph SQLite[runtime/advanced_agent.sqlite]
    HOOKS[runtime_hooks<br/>persistent maintenance queue]
    EVENTS[semantic_events<br/>cleaned TTY semantic chunks]
    SUMS[semantic_summaries<br/>small-model/runtime compression]
    TASKS[semantic_tasks<br/>compaction task state]
    CANDS[semantic_memory_candidates<br/>candidate approval state]
    MEM[memory_items + vectors + FTS<br/>approved durable memory]
    MSG[messages / interaction_streams<br/>raw tail / ordinary session context]
  end

  subgraph WAL[SQLite WAL files]
    WALF[advanced_agent.sqlite-wal]
    SHM[advanced_agent.sqlite-shm]
  end
```

当前限制/策略：

- `runtime/codex_interactive` 只保留最近 32 个 Codex session。
- 每个 `.terminal.log` 是清洗后的 TTY 内容，最大 5 MiB。
- `semantic_events/summaries/tasks/candidates` 是 runtime 状态，不是长期记忆。
- 只有 `memory_items` 是 durable long-term memory。
- SQLite WAL 可能临时变大，属于正常 WAL 行为，可通过 checkpoint 收缩。

## 3. 数据处理主流程

```mermaid
sequenceDiagram
  participant User
  participant Wrapper as codexx wrapper
  participant Agent as Codex/TTY agent
  participant Store as SQLite semantic store
  participant Hook as runtime_hooks
  participant BG as BackgroundRuntimeQueue
  participant Small as memory_model
  participant Big as memory_write_model
  participant Memory as durable memory

  User->>Wrapper: keystrokes / paste / Enter
  Wrapper->>Agent: forward raw TTY input
  Wrapper->>Store: best-effort user_submit event

  Agent-->>Wrapper: TTY output
  Wrapper->>Wrapper: ANSI/OSC strip, CR overwrite normalize
  Wrapper->>Store: cleaned_tty_chunk event
  Wrapper->>Wrapper: append to 1 MiB in-memory semantic ring
  Wrapper->>Wrapper: append cleaned bounded terminal log

  alt 3 user submits or buffer pressure
    Wrapper->>Hook: schedule semantic_maintenance
  end

  alt session close / Ctrl-C / interrupt
    Wrapper->>Store: session_close / interrupt event
    Wrapper->>Hook: schedule semantic_maintenance and memory_maintenance
    Note over Wrapper,BG: shutdown does not run heavy hooks unless flush_on_stop=true
  end

  BG->>Hook: normal runtime tick reads due hooks
  Hook->>BG: semantic_maintenance
  BG->>Store: create/lock semantic task
  BG->>Small: summarize older semantic events
  Small-->>BG: rolling summary
  BG->>Store: transactionally insert semantic_summary and compact source events

  alt close/interrupt candidate only
    BG->>Store: create semantic_memory_candidate
    BG->>Big: approve/reject candidate with small evidence + related memories
    Big-->>BG: tool-call decision
    alt approved
      BG->>Memory: write durable memory_items/vectors
      BG->>Store: mark candidate succeeded
    else rejected/no model
      BG->>Store: rejected or awaiting_approval_model
    end
  end
```

## 4. Shutdown / Ctrl-C 行为

```mermaid
flowchart TD
  CTRL[Ctrl-C / SIGTERM] --> PTY[_run_pty exits / terminates child process]
  PTY --> FINAL[wrapper finally block]
  FINAL --> SE[write session_close semantic event]
  FINAL --> HK[schedule maintenance hooks in runtime_hooks]
  FINAL --> STOP[BackgroundRuntimeQueue.stop]
  STOP --> FILTER{shutdown flush?}
  FILTER -->|only payload.flush_on_stop=true| FAST[run explicit quick hooks]
  FILTER -->|default heavy hooks skipped| PERSIST[persist hooks for next normal tick]
  FAST --> EXIT[exit without traceback]
  PERSIST --> EXIT
```

Important points:

- Ctrl-C should prioritize quick exit.
- Model-heavy summary/profile/memory approval hooks are not run during shutdown flush by default.
- The hook remains in SQLite and is picked up on the next normal runtime tick.
- `kill -9` cannot run exit handlers, but already committed semantic events/tasks remain recoverable.

## 5. Long-term memory boundary

```mermaid
flowchart LR
  SE[semantic_events] -->|runtime only| SUM[semantic_summaries]
  SUM -->|runtime only| CAND[semantic_memory_candidates]
  CAND -->|memory_write_model approval| MEM[memory_items durable memory]

  TOOL[MCP memory_write / explicit user request] --> MEM
  PROFILE[profile maintenance<br/>small observer + major writer] --> MEM
```

What does **not** directly become long-term memory:

- cleaned terminal logs
- semantic events
- semantic summaries
- raw codex_tail
- routine three-user-turn compactions

What may become long-term memory:

- explicit `memory_write`
- profile/behavior records approved by the major writer
- close/interrupt semantic candidates approved by the major writer

This keeps the semantic layer as a small context/compression window rather than
polluting durable memory with noisy terminal history.

## 6. API/model call locations

```mermaid
flowchart TB
  Codex[Codex CLI] -->|normal model calls| CodexAPI[Codex/OpenAI API configured by Codex]

  Wrapper[codexx runtime] -->|memory_model| Cheap[Small/cheap model API<br/>semantic summaries, profile observer]
  Wrapper -->|memory_write_model| Strong[Strong/approval model API<br/>durable memory gatekeeper]

  MCP[MCP tools] -->|memory_write explicit| DB[(SQLite/vector memory)]
```

Cost control:

- Routine semantic compaction calls only the small model.
- Long-term memory approval is limited to close/interrupt candidates.
- Shutdown does not run heavy model hooks by default.
- Direct explicit memory writes bypass model approval because the user/tool call
  is already an explicit durable-memory action.
