# Prompt Builder

Prompts must not be scattered across agents. `PromptBuilder` is the central prompt assembly path.

## Inputs

- role-specific base instructions;
- prompt overlays from `prompt_overlays`;
- bounded recent context from `ContextBuilder`;
- vector-retrieved memories;
- latest user message;
- main decision text for interactive rendering.

## Current builders

- `interactive_quick(user_text)`
- `interactive_render(main_text)`
- `main_decision(session_id, request_id, user_text)`

Agents should call PromptBuilder instead of hardcoding long prompts internally.
