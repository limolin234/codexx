# Automation Hooks

Manual memory/profile maintenance is not realistic. Maintenance must be hook-driven and automatic.

## Principle

Models can request hooks, but the runtime owns scheduling and execution.

A hook usually wakes an internal component such as main-agent or preference-worker. It does not imply speaking to the user.

## Current automated path

```text
user message
  -> RuntimeApp.start_user_request
  -> HookStore.ensure_unique(PREFERENCE_MAINTENANCE, session)
  -> AutomationEngine.tick
  -> PreferenceWorker.update_from_session
  -> user_profiles / prompt_overlays
  -> runtime_events hook.fired
```

## Future hooks

- `CHECK_STATE`: wake main-agent to inspect tasks/session state.
- `MEMORY_INDEX`: index new memory candidates into sqlite-vec.
- `COMPACT_MEMORY`: compact/cleanup old memory and conversations.
- `PREFERENCE_MAINTENANCE`: update bounded user profile and prompt overlays.
