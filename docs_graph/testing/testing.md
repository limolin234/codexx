# Testing

Use the project `.venv` when running tests and local scripts.

## Common validation

```bash
python -m pytest -q
```

If the active shell has not activated the project venv, prefer:

```bash
.venv/bin/python -m pytest -q
```

For shell script syntax checks:

```bash
bash -n scripts/install.sh scripts/remove_guidance.sh bin/codexx bin/advanced-agentd bin/advanced-agent-mcp
```

## Smoke checks

Runtime/memory split checks should verify:

- runtime DB does not own durable memory vector tables
- `memory/longterm.sqlite` initializes durable memory tables
- `memory/rawtail.sqlite` initializes raw-tail tables
- MCP tests are not polluted by current environment sidecar DB variables

## Detailed docs

- `docs/testing_strategy.md`
- `docs/migrations_doctor.md`
