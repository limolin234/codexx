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
  -> optional process cwd sync for MCP/server subprocesses
```

`WorkspaceState` is still the authority.  Runtime components that need a real
process cwd can opt into process-cwd sync; this makes `workdir.chdir` call
`os.chdir()` in that same runtime process after validation.

For wrapped interactive Codex, the wrapper also polls the Codex child process
cwd on Linux via `/proc/<pid>/cwd`.  If Codex itself changes its cwd at runtime,
the wrapper notices and updates Advanced Agent's runtime cwd to follow it.
This is one-way observation: a parent process cannot directly `chdir` an
already-running Codex child from the outside.  Pushing cwd into Codex native
tools still requires Codex itself to support a runtime cwd change or a restart
with `-C`.

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

## Wrapped Codex defaults

`codexx` starts the project-local MCP server in the caller launch cwd, not in
the Advanced Agent checkout.  The MCP server receives the checkout through an
absolute `PYTHONPATH`, so imports remain stable while cwd semantics match the
global-agent workspace.
