# Testing Strategy

The project is expected to live for a long time. Tests are separated by responsibility to avoid external integrations breaking the core.

## Layout

```text
tests/core/         core stores, runtime primitives, config, process runner
tests/integration/  cross-module flows
tests/plugins/      external plugin interface and hard validation
```

## Plugin safety

Plugin manifests are treated as untrusted input. Validation rules:

- plugin name must be simple and path-safe;
- hook kind must stay inside `plugin.<name>.*`;
- hook target must start with `plugin:`;
- repeat interval must not be too aggressive;
- payload size is capped;
- plugin hooks produce `plugin.hook.requested` events instead of calling core internals directly.

External modules should fail closed when invalid.
