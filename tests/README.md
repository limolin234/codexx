# Test Layout

- `core/`: core stores, runtime primitives, process runner, config, infrastructure.
- `integration/`: cross-module flows such as automation, Codex worker, compaction, preferences, vector memory.
- `plugins/`: external plugin interface and validation tests.

External/plugin tests should be stricter than normal feature tests. Plugins must not be able to register hooks outside their namespace or target core runtime components directly.
