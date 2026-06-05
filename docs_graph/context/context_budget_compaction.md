# Context Budget and Compaction

Dialogue context should stay short. With vector memory available, raw conversation does not need to occupy a large fraction of the model context.

## Policy

Use a flexible budget:

- compact when live uncompacted dialogue exceeds 50% of max context budget;
- keep a recent short-term window;
- compact older prefix into vector memory;
- retrieve relevant compacted memory when needed.

## Current implementation

- `ContextBudget`: character-based approximation of context budget.
- `ConversationCompactor`: compacts old session messages into `session_summary` memory and sqlite-vec vectors.
- `ContextBuilder`: builds bounded main-agent context from recent messages plus vector retrieval.

Token-accurate budgeting can replace the char approximation later.
