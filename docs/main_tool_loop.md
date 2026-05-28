# Main Agent Tool-Call Loop

Main agent can use official OpenAI-style tool calling at the model boundary while
runtime execution remains provider-neutral.

## Flow

```text
PromptBuilder.main_decision()
  -> model.chat_complete(messages, tools=OpenAIToolAdapter.tool_schemas())
  -> tool_calls[]
  -> OpenAIToolAdapter.request_from_tool_call()
  -> CapabilityExecutor.execute()
  -> tool result as role=tool message
  -> model.chat_complete(...)
  -> final main decision
  -> main_decisions
  -> InteractiveAgent.render_main_reply()
```

## Constraints

- Max tool rounds are bounded to avoid infinite model/tool loops.
- Main sees only high-level capabilities, not raw shell/file/process tools.
- Runtime/audit/supervisor own actual execution and control semantics.
- The user still talks through interactive; main decisions are rendered by
  interactive for consistency.

## First supported capabilities

- `task_state`
- `task_tail`
- `task_history`
- `memory_search`
- `hook_schedule`
- `interrupt_request`
- `spawn_task`

## Async model path

`OpenAICompatibleClient` supports both sync and async calls:

- `chat_complete(...)` uses stdlib `urllib` for simple synchronous execution.
- `chat_complete_async(...)` uses `httpx.AsyncClient` for background/nonblocking
  main-agent runs.

`RuntimeApp.start_user_request_background()` uses `MainAgent.handle_request_async()`
so future model/network latency can yield to the runtime loop while preserving the
same CapabilityExecutor boundary.
