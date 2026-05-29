from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import threading


@dataclass(slots=True)
class WorkspaceInfo:
    cwd: str
    project_root: str
    markers: list[str]


class WorkspaceState:
    """Runtime working-directory state for a system-level local agent.

    This deliberately is not tied to the project checkout.  The agent can move
    between directories like a shell; task spawning and project_info should use
    this state instead of the Python process cwd.
    """

    def __init__(self, cwd: str | Path | None = None, *, sync_process_cwd: bool = False) -> None:
        self._lock = threading.RLock()
        self._sync_process_cwd = sync_process_cwd
        self._cwd = self._resolve(cwd or Path.cwd(), base=Path.cwd())
        if self._sync_process_cwd:
            os.chdir(self._cwd)

    @property
    def cwd(self) -> Path:
        with self._lock:
            return self._cwd

    def chdir(self, path: str | Path) -> WorkspaceInfo:
        with self._lock:
            new_cwd = self._resolve(path, base=self._cwd)
            if not new_cwd.exists():
                raise FileNotFoundError(str(new_cwd))
            if not new_cwd.is_dir():
                raise NotADirectoryError(str(new_cwd))
            self._cwd = new_cwd
            if self._sync_process_cwd:
                os.chdir(new_cwd)
            return self.info()

    def info(self) -> WorkspaceInfo:
        with self._lock:
            root = self.find_project_root(self._cwd)
            return WorkspaceInfo(cwd=str(self._cwd), project_root=str(root), markers=self.project_markers(root))

    def find_project_root(self, start: Path | None = None) -> Path:
        markers = ("pyproject.toml", ".git", "AGENT.md", "AGENTS.md")
        current = (start or self._cwd).resolve()
        for parent in (current, *current.parents):
            if any((parent / marker).exists() for marker in markers):
                return parent
        return current

    def project_markers(self, root: Path) -> list[str]:
        return [marker for marker in ("pyproject.toml", ".git", "AGENT.md", "AGENTS.md") if (root / marker).exists()]

    def _resolve(self, path: str | Path, base: Path) -> Path:
        raw = Path(path).expanduser()
        if not raw.is_absolute():
            raw = base / raw
        return raw.resolve()
