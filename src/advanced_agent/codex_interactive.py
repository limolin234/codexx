from __future__ import annotations

import argparse
import fcntl
import os
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import termios
import time
import tomllib
import tty
from dataclasses import dataclass
from pathlib import Path

from advanced_agent import defaults
from advanced_agent.memory_indexer import MemoryCandidate
from advanced_agent.runtime.app import RuntimeApp
from advanced_agent.models import new_id


@dataclass(slots=True)
class CodexInteractiveSession:
    session_id: str
    codex_session_id: str
    log_path: Path
    returncode: int


DEFAULT_BOOTSTRAP_CHARS = 0


CODEXX_RUNTIME_INSTRUCTIONS_FALLBACK = """# codexx runtime instructions

You are running under the `codexx` wrapper. Keep the user's current working
directory instructions separate from Advanced Agent wrapper/runtime behavior.
Use Advanced Agent MCP tools (`context_get`, `memory_search`, `memory_write`,
`session_raw_tail`, `project_info`, `workdir_chdir`) as the durable memory and
runtime layer. On the first non-trivial request, call `context_get` before
answering. Do not treat Codex-side MEMORY.md files as the primary Advanced Agent
memory source unless the user explicitly asks to audit or migrate them.
"""


BOOTSTRAP_INSTRUCTION = """Advanced Agent bootstrap context.

You are running inside the `codexx` wrapper. The following is a bounded recent-history excerpt, not the full conversation.
Use it as startup context so the user does not need to restate the last work.

Rules:
- Treat Advanced Agent MCP memory as trusted project memory.
- If the excerpt is insufficient, call `context_get` for prior project/session context.
- If you need more raw recent dialogue, call `session_raw_tail`.
- For durable decisions, preferences, progress, and handoffs, call `memory_write`.
- Do not claim there is no previous context before checking the available MCP tools.
"""


def build_codex_env(app: RuntimeApp, session_id: str, db_path: str, log_path: Path, project_root: str | Path | None = None) -> dict[str, str]:
    project_root_path = Path(project_root) if project_root is not None else _package_project_root()
    env = os.environ.copy()
    env.update({
        "ADVANCED_AGENT_SESSION": session_id,
        "ADVANCED_AGENT_DB": str(db_path),
        "ADVANCED_AGENT_CODEX_LOG": str(log_path),
        "ADVANCED_AGENT_ROOT": str(project_root_path),
        "ADVANCED_AGENT_PROJECT_ROOT": str(project_root_path),
        "ADVANCED_AGENT_LAUNCH_CWD": str(Path.cwd()),
        "ADVANCED_AGENT_SCOPE": defaults.default_scope(),
        "ADVANCED_AGENT_MEMORY_TRUST": "high",
        "ADVANCED_AGENT_MCP_HINT": "Use context_get/memory_search before denying previous context; use memory_write for records and handoffs.",
    })
    return env


def _package_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_runtime_path(path: str | Path, project_root: str | Path | None = None) -> Path:
    runtime_path = Path(path)
    if runtime_path.is_absolute():
        return runtime_path
    return (Path(project_root) if project_root is not None else _package_project_root()) / runtime_path


def _codex_config_path() -> Path:
    codex_home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
    return codex_home / "config.toml"


def _configured_model_instructions_path(config_path: str | Path | None = None) -> Path | None:
    path = Path(config_path) if config_path is not None else _codex_config_path()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, tomllib.TOMLDecodeError, OSError):
        return None
    value = data.get("model_instructions_file")
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value).expanduser()


def _codexx_runtime_instructions(project_root: str | Path | None = None) -> str:
    root = Path(project_root) if project_root is not None else _package_project_root()
    source = root / "docs" / "codexx_runtime_instructions.md"
    try:
        text = source.read_text(encoding="utf-8").strip()
    except OSError:
        text = CODEXX_RUNTIME_INSTRUCTIONS_FALLBACK.strip()
    return text


def build_combined_model_instructions(
    output_path: str | Path,
    *,
    project_root: str | Path | None = None,
    user_instructions_path: str | Path | None = None,
) -> Path:
    """Write a per-wrapper model instruction file without mutating Codex config.

    Codex accepts one `model_instructions_file`.  To avoid clobbering the user's
    normal global instructions, `codexx` generates a temporary combined file:
    global user instructions first, then the small codexx runtime contract.
    """

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    user_path = Path(user_instructions_path).expanduser() if user_instructions_path is not None else _configured_model_instructions_path()
    parts: list[str] = []
    if user_path is not None:
        try:
            user_text = user_path.read_text(encoding="utf-8").strip()
        except OSError:
            user_text = ""
        if user_text:
            parts.extend(["# User Codex instructions", "", user_text, ""])
    parts.extend([
        "# Advanced Agent codexx wrapper instructions",
        "",
        _codexx_runtime_instructions(project_root),
        "",
    ])
    out.write_text("\n".join(parts), encoding="utf-8")
    return out


def codex_mcp_config_args(
    db_path: str,
    config_path: str | Path | None = None,
    server_name: str | None = None,
    project_root: str | Path | None = None,
    launch_cwd: str | Path | None = None,
) -> list[str]:
    """Return Codex `-c` overrides for the project-local MCP server.

    This keeps the entrypoint self-contained: launching our wrapper is enough
    for Codex to see Advanced Agent tools, without mutating global
    `~/.codex/config.toml`.
    """

    project_root_path = Path(project_root) if project_root is not None else _package_project_root()
    launch_cwd_path = Path(launch_cwd) if launch_cwd is not None else Path.cwd()
    config_path = config_path if config_path is not None else defaults.default_config()
    server_name = server_name or defaults.default_mcp_server_name()
    server = f"mcp_servers.{server_name}"
    args = [
        "-c",
        f'{server}.command="{sys.executable}"',
        "-c",
        f'{server}.args=["-m","advanced_agent.mcp_server","--db","{db_path}","--config","{config_path or ""}"]',
        "-c",
        f'{server}.env={{PYTHONPATH="{project_root_path / "src"}",ADVANCED_AGENT_DB="{db_path}",ADVANCED_AGENT_CONFIG="{config_path or ""}",ADVANCED_AGENT_SCOPE="{defaults.default_scope()}",ADVANCED_AGENT_MEMORY_TRUST="high",ADVANCED_AGENT_LAUNCH_CWD="{launch_cwd_path}"}}',
        "-c",
        f'{server}.cwd="{launch_cwd_path}"',
    ]
    return args


def build_bootstrap_prompt(app: RuntimeApp, session_id: str, max_chars: int = 1200) -> str:
    """Build the initial prompt passed to Codex when the user gives no prompt.

    This intentionally stays small. It gives Codex enough recent context to
    continue naturally, while pointing it to MCP tools for deeper raw tail and
    long-term memory retrieval.
    """

    max_chars = max(0, int(max_chars))
    lines = app.sessions.raw_tail_lines(session_id, limit=40, max_chars=400, include_compacted=True)
    selected: list[str] = []
    total = 0
    for line in reversed(lines):
        if total + len(line) + 1 > max_chars:
            break
        selected.append(line)
        total += len(line) + 1
    selected.reverse()
    excerpt = "\n".join(selected).strip() or "(no recent raw dialogue in Advanced Agent runtime yet)"
    return "\n".join([
        BOOTSTRAP_INSTRUCTION.strip(),
        "",
        f"Advanced Agent session_id: {session_id}",
        f"Runtime scope: {defaults.default_scope()}",
        f"Recent raw tail excerpt, bounded to about {max_chars} chars:",
        "```text",
        excerpt,
        "```",
        "",
        "Continue interactively. If the user says to continue previous work, first use this excerpt; then call context_get/session_raw_tail/memory_search as needed.",
    ])


def should_inject_bootstrap(codex_args: list[str]) -> bool:
    """Return true when Codex is being launched without an explicit prompt.

    Codex accepts an optional positional prompt. We only append our bootstrap
    prompt for plain interactive launches; if the user supplied a prompt or a
    subcommand, do not alter argv semantics.
    """

    if not codex_args:
        return True
    known_flags_with_value = {"-c", "--config", "-i", "--image", "-m", "--model", "--local-provider", "-p", "--profile", "--profile-v2", "-s", "--sandbox", "-C", "--cd", "--add-dir", "-a", "--ask-for-approval", "--remote", "--remote-auth-token-env"}
    commands = {
        "exec",
        "e",
        "review",
        "login",
        "logout",
        "mcp",
        "plugin",
        "mcp-server",
        "app-server",
        "remote-control",
        "completion",
        "update",
        "doctor",
        "sandbox",
        "debug",
        "apply",
        "a",
        "resume",
        "fork",
        "cloud",
        "exec-server",
        "features",
        "help",
    }
    skip_next = False
    for arg in codex_args:
        if skip_next:
            skip_next = False
            continue
        if arg == "--":
            continue
        if arg in known_flags_with_value:
            skip_next = True
            continue
        if any(arg.startswith(prefix + "=") for prefix in known_flags_with_value if prefix.startswith("--")):
            continue
        if arg.startswith("-"):
            continue
        return False
    return True


def run_interactive_codex(
    app: RuntimeApp,
    db_path: str,
    codex_args: list[str],
    log_dir: str | Path = defaults.DEFAULT_LOG_DIR,
    session_title: str = defaults.DEFAULT_SESSION_TITLE,
    config_path: str | Path | None = None,
    enable_mcp: bool = True,
    project_root: str | Path | None = None,
    bootstrap_chars: int = DEFAULT_BOOTSTRAP_CHARS,
) -> CodexInteractiveSession:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise RuntimeError("interactive Codex wrapper requires a TTY")
    session_id = app.default_session(session_title)
    codex_session_id = new_id("codexsess")
    project_root_path = Path(project_root) if project_root is not None else _package_project_root()
    log_root = _resolve_runtime_path(log_dir, project_root_path)
    log_root.mkdir(parents=True, exist_ok=True)
    log_path = log_root / f"{codex_session_id}.terminal.log"
    instruction_path = build_combined_model_instructions(
        log_root / f"{codex_session_id}.instructions.md",
        project_root=project_root_path,
    )
    instruction_args = ["-c", f'model_instructions_file="{instruction_path}"']
    injected_args = codex_mcp_config_args(db_path, config_path, project_root=project_root_path, launch_cwd=app.workspace.cwd) if enable_mcp else []
    if bootstrap_chars > 0 and should_inject_bootstrap(codex_args):
        codex_args = [*codex_args, build_bootstrap_prompt(app, session_id, max_chars=bootstrap_chars)]
    command = ["codex", *instruction_args, *injected_args, *codex_args]
    returncode = _run_pty(command, build_codex_env(app, session_id, db_path, log_path, project_root_path), log_path, child_cwd_callback=lambda cwd: app.chdir(str(cwd)))
    _ingest_codex_log_tail(app, session_id, codex_session_id, log_path)
    return CodexInteractiveSession(session_id=session_id, codex_session_id=codex_session_id, log_path=log_path, returncode=returncode)


def _run_pty(command: list[str], env: dict[str, str], log_path: Path, child_cwd_callback=None) -> int:
    master_fd, slave_fd = pty.openpty()
    _copy_winsize(sys.stdin.fileno(), slave_fd)
    proc = subprocess.Popen(command, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd, env=env, close_fds=True, start_new_session=True)
    os.close(slave_fd)
    old_tty_attrs = termios.tcgetattr(sys.stdin.fileno())

    def _handle_winch(*_: object) -> None:
        _copy_winsize(sys.stdin.fileno(), master_fd)

    old_handler = signal.signal(signal.SIGWINCH, _handle_winch)
    last_child_cwd: str | None = None
    last_child_cwd_poll = 0.0

    def _poll_child_cwd() -> None:
        nonlocal last_child_cwd, last_child_cwd_poll
        if child_cwd_callback is None:
            return
        now = time.monotonic()
        if now - last_child_cwd_poll < 0.25:
            return
        last_child_cwd_poll = now
        try:
            child_cwd = os.readlink(f"/proc/{proc.pid}/cwd")
        except OSError:
            return
        if child_cwd == last_child_cwd:
            return
        last_child_cwd = child_cwd
        try:
            child_cwd_callback(Path(child_cwd))
        except Exception:
            return

    try:
        # The wrapper is a PTY proxy. The parent terminal must be raw too;
        # otherwise arrows/control keys are line-buffered and Codex receives
        # escape sequences like "^[[C" as literal text after Enter.
        tty.setraw(sys.stdin.fileno())
        with log_path.open("ab") as log:
            while True:
                _poll_child_cwd()
                readable, _, _ = select.select([sys.stdin.fileno(), master_fd], [], [], 0.25)
                if master_fd in readable:
                    try:
                        data = os.read(master_fd, 4096)
                    except OSError:
                        break
                    if not data:
                        break
                    os.write(sys.stdout.fileno(), data)
                    log.write(data)
                    log.flush()
                if sys.stdin.fileno() in readable:
                    data = os.read(sys.stdin.fileno(), 4096)
                    if not data:
                        break
                    if b"\x03" in data:
                        log.write(b"\n[WRAPPER_CTRL_C_INTERRUPTED]\n")
                        log.flush()
                        _terminate_process_group(proc)
                        return 130
                    os.write(master_fd, data)
                    log.write(b"\n[USER_INPUT_BYTES]\n")
                    log.write(data)
                    log.flush()
                if proc.poll() is not None:
                    # Drain remaining PTY output if any.
                    while True:
                        readable, _, _ = select.select([master_fd], [], [], 0)
                        if not readable:
                            break
                        try:
                            data = os.read(master_fd, 4096)
                        except OSError:
                            break
                        if not data:
                            break
                        os.write(sys.stdout.fileno(), data)
                        log.write(data)
                    break
    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_tty_attrs)
        signal.signal(signal.SIGWINCH, old_handler)
        os.close(master_fd)
    return proc.wait()


def _terminate_process_group(proc: subprocess.Popen) -> None:
    """Stop the wrapped Codex process promptly on wrapper-level Ctrl+C."""

    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGINT)
    except ProcessLookupError:
        return
    except OSError:
        proc.terminate()
    try:
        proc.wait(timeout=1.0)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        proc.terminate()
    try:
        proc.wait(timeout=1.0)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        proc.kill()
    try:
        proc.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        return


def _copy_winsize(src_fd: int, dst_fd: int) -> None:
    try:
        winsize = fcntl.ioctl(src_fd, termios.TIOCGWINSZ, b"\0" * 8)
        rows, cols, xpixels, ypixels = struct.unpack("HHHH", winsize)
        if rows and cols:
            fcntl.ioctl(dst_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, xpixels, ypixels))
    except OSError:
        return


ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


def _clean_terminal_log(text: str, max_chars: int = 6000) -> str:
    cleaned = ANSI_RE.sub("", text)
    cleaned = cleaned.replace("\r", "\n")
    lines = []
    blank = False
    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped:
            if not blank:
                lines.append("")
            blank = True
            continue
        blank = False
        lines.append(stripped)
    return "\n".join(lines)[-max_chars:]


def _ingest_codex_log_tail(app: RuntimeApp, session_id: str, codex_session_id: str, log_path: Path, max_chars: int = 12_000) -> None:
    try:
        raw = log_path.read_bytes()[-max_chars:].decode("utf-8", errors="replace")
    except FileNotFoundError:
        return
    cleaned = _clean_terminal_log(raw)
    if not cleaned.strip():
        return
    interrupted = "[WRAPPER_CTRL_C_INTERRUPTED]" in raw
    summary_suffix = " interrupted and saved" if interrupted else " transcript tail"
    candidate = MemoryCandidate(
        scope="project:advanced_agent",
        type="codex_interactive_log",
        summary=f"Interactive Codex session {codex_session_id}{summary_suffix}",
        content=cleaned,
        source_type="codex_interactive",
        source_id=codex_session_id,
        importance=0.55 if interrupted else 0.4,
        confidence=0.6,
    )
    app.memory_indexer.index(candidate, agent_role="codex")
    _ingest_session_raw_tail_handoff(app, session_id, codex_session_id)
    app.events.publish("codex.interactive.logged", "codex_wrapper", {"session_id": session_id, "codex_session_id": codex_session_id, "log_path": str(log_path)})


def _ingest_session_raw_tail_handoff(app: RuntimeApp, session_id: str, codex_session_id: str, max_chars: int = 4000) -> None:
    tail = "\n".join(app.sessions.raw_tail_lines(session_id, limit=30, max_chars=500, include_compacted=True)).strip()
    if not tail:
        return
    candidate = MemoryCandidate(
        scope=defaults.default_scope(),
        type="handoff",
        summary=f"Codex wrapper closing raw-tail handoff {codex_session_id}",
        content=tail[-max_chars:],
        source_type="codex_wrapper_raw_tail",
        source_id=codex_session_id,
        importance=0.65,
        confidence=0.7,
        facets={
            "handoff": tail[-1200:],
            "time": tail[-1200:],
            "chat": tail[-1200:],
        },
    )
    app.memory_indexer.index(candidate, agent_role="codex")


def main() -> None:
    parser = argparse.ArgumentParser(description="Enhanced interactive Codex wrapper with Advanced Agent logging/memory.")
    parser.add_argument("--db", default=defaults.default_db())
    parser.add_argument("--config", default=defaults.default_config())
    parser.add_argument("--session-title", default=defaults.default_session_title())
    parser.add_argument("--log-dir", default=defaults.default_log_dir())
    parser.add_argument("--project-root", default=os.environ.get("ADVANCED_AGENT_PROJECT_ROOT"), help="Advanced Agent project root for runtime files/MCP server. Codex still opens in the caller's current directory.")
    parser.add_argument("--bootstrap-chars", type=int, default=int(os.environ.get("ADVANCED_AGENT_BOOTSTRAP_CHARS", str(DEFAULT_BOOTSTRAP_CHARS))), help="Opt-in: inject this many chars of recent Advanced Agent raw-tail context as Codex's initial prompt when no prompt/subcommand is supplied. Default 0 keeps startup quiet; use MCP recall on the first real request instead.")
    parser.add_argument("--no-mcp", action="store_true", help="Do not inject the project-local Advanced Agent MCP server into Codex.")
    parser.add_argument("codex_args", nargs=argparse.REMAINDER, help="Arguments passed through to codex. Use -- before codex args if needed.")
    args = parser.parse_args()
    codex_args = args.codex_args[1:] if args.codex_args[:1] == ["--"] else args.codex_args
    project_root = Path(args.project_root) if args.project_root else _package_project_root()
    db_path = _resolve_runtime_path(args.db, project_root)
    config_path = _resolve_runtime_path(args.config, project_root)
    app = RuntimeApp.create(db_path, config_path=config_path)
    result = run_interactive_codex(app, str(db_path), codex_args, log_dir=args.log_dir, session_title=args.session_title, config_path=str(config_path), enable_mcp=not args.no_mcp, project_root=project_root, bootstrap_chars=args.bootstrap_chars)
    print(f"\n[advanced_agent] codex session logged: {result.log_path} rc={result.returncode}")
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
