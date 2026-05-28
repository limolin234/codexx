# Architecture Diagrams

These diagrams are normative. New implementation should follow these flows instead of relying on implicit cross-calls.

## 1. Process / role topology

```mermaid
flowchart TD
    U[User] --> IA[Interactive Agent]
    IA --> S[Supervisor / Runtime]
    S --> MA[Main Agent]
    S --> AA[Audit Agent]
    S --> TW[Task Worker / Codex]
    S --> MW[Memory & Preference Workers]
    S --> PR[Plugin Workers]
    S --> DB[(SQLite)]
    S --> V[(sqlite-vec)]
    TW --> S
    MW --> DB
    MW --> V
    PR --> S
```

## 2. User request flow

```mermaid
sequenceDiagram
    participant User
    participant IA as Interactive Agent
    participant RT as Runtime/Supervisor
    participant MA as Main Agent
    participant DS as MainDecisionStore
    participant AU as Audit Agent

    User->>IA: user message
    IA->>RT: provisional stream delta
    RT->>MA: request semantic decision
    MA->>DS: persist main_decision
    MA->>RT: decision id
    RT->>AU: review if needed
    RT->>IA: render decision.user_visible_instruction
    IA->>User: authoritative user-facing reply
```

## 3. Task / Codex progress inspection

```mermaid
flowchart TD
    MA[Main Agent] -->|spawn request| S[Supervisor]
    S -->|audit| AU[Audit]
    S -->|start| CW[CodexTaskWorker]
    CW --> ASP[AsyncSubprocessRunner]
    ASP -->|stdout/stderr| TB[TailBuffer]
    ASP -->|output callback| TS[(TaskStore)]
    TS --> TE[task_events]
    TS --> TO[task_output_chunks]
    TS --> SUM[task_summaries]
    MA -->|read-only| TS
    IA[Interactive Agent] -->|read-only summary| TS
```

## 4. Memory indexing and retrieval

```mermaid
flowchart TD
    SRC[Messages / Task summaries / Compaction] --> MC[Memory Candidate]
    MC --> AL[Memory Alignment Agent]
    AL --> MI[(memory_items)]
    AL --> VL[Vector Labels]
    VL --> VV[(sqlite-vec vectors)]
    VV --> SEARCH[Vector Search]
    MI --> HYD[SQLite Hydration]
    SEARCH --> HYD
    HYD --> CB[ContextBuilder]
    CB --> MA[Main Agent]
    CB --> IA[Interactive Agent]
```

## 5. Hook automation

```mermaid
flowchart TD
    E[Runtime Event / User Message] --> HS[HookStore]
    HS --> AE[AutomationEngine.tick]
    AE -->|PREFERENCE_MAINTENANCE| PW[PreferenceWorker]
    AE -->|COMPACT_MEMORY| CC[ConversationCompactor]
    AE -->|MEMORY_INDEX| IDX[MemoryIndexer future]
    AE -->|plugin.*| PH[plugin.hook.requested]
    PW --> PROF[(user_profiles)]
    PW --> PO[(prompt_overlays)]
    CC --> MEM[(memory_items + sqlite-vec)]
```

## 6. Plugin hook flow

```mermaid
sequenceDiagram
    participant PM as Plugin Manifest
    participant REG as PluginRegistry
    participant HS as HookStore
    participant AE as AutomationEngine
    participant EV as EventBus
    participant PA as Plugin Agent

    PM->>REG: load plugins/name/plugin.json
    REG->>HS: schedule default plugin hooks
    AE->>HS: due hooks
    AE->>EV: plugin.hook.requested
    PA->>EV: consume/observe event
    PA->>PA: read external data / write artifact
```
