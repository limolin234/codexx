# Runtime working directory control

Advanced Agent is intended to become a system-level local AI, not only a
project-local helper. Therefore `cd` is a runtime built-in, not a shell command
that only affects one subprocess.

## Model

```text
WorkspaceState.cwd
  -> project_info / workdir.chdir
  -> CLI prompt commands
  -> task spawn default workdir
```

The Python process cwd can remain the Advanced Agent checkout for import/config
stability. Runtime work happens relative to `WorkspaceState.cwd`.

## Tools

- `project.info` / `project_info`: read current runtime cwd and inferred project
  root.
- `workdir.chdir` / `workdir_chdir`: change runtime cwd. Relative paths resolve
  from the current runtime cwd, not necessarily from the agent checkout.

## CLI built-ins

- `/pwd`: show runtime cwd and project root.
- `/cd PATH`: update runtime cwd.

Normal user text such as `cd ~/MyProjects/foo` can also be handled by the main
agent through the `workdir_chdir` capability.
