from __future__ import annotations

import re
import codecs
import os
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path


ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


def normalize_carriage_returns(text: str) -> str:
    """Treat bare CR as line overwrite instead of always expanding history."""

    lines: list[str] = []
    current = ""
    index = 0
    while index < len(text):
        ch = text[index]
        if ch == "\r":
            if index + 1 < len(text) and text[index + 1] == "\n":
                lines.append(current)
                current = ""
                index += 2
                continue
            current = ""
        elif ch == "\n":
            lines.append(current)
            current = ""
        else:
            current += ch
        index += 1
    if current:
        lines.append(current)
    return "\n".join(lines)


def clean_terminal_text(text: str, max_chars: int | None = 6000) -> str:
    cleaned = re.sub(r"\x1b\][^\x07]*(?:\x07|\x1b\\)", "", text)
    cleaned = ANSI_RE.sub("", cleaned)
    cleaned = normalize_carriage_returns(cleaned)
    cleaned = re.sub(r"\n?\[USER_INPUT_BYTES\]\n?", "\n", cleaned)
    cleaned = re.sub(r"(?:\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*(?:\x07|\x1b\\)|\x1b.|\x0f|\x0e|\x07)", "", cleaned)
    cleaned = re.sub(r"0;[⠇⠏⠋⠙⠹⠸⠼⠴⠦⠧] [^\n]{0,120}", "", cleaned)
    lines = []
    blank = False
    previous = None
    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped:
            if not blank:
                lines.append("")
            blank = True
            previous = stripped
            continue
        blank = False
        if stripped == previous:
            continue
        previous = stripped
        lines.append(stripped)
    cleaned_text = "\n".join(lines)
    if max_chars is None:
        return cleaned_text
    return cleaned_text[-max_chars:]


@dataclass(slots=True)
class SemanticChunk:
    kind: str
    text: str
    payload: dict = field(default_factory=dict)


class GenericTtyInputTracker:
    """Best-effort cross-TUI user submit tracker from raw terminal input."""

    def __init__(self, max_submit_chars: int = 4000) -> None:
        self.max_submit_chars = max_submit_chars
        self._chars: list[str] = []
        self._escape = False
        self._decoder = codecs.getincrementaldecoder("utf-8")("ignore")

    def observe(self, data: bytes) -> list[SemanticChunk]:
        chunks: list[SemanticChunk] = []
        for byte in data:
            if self._escape:
                if 0x40 <= byte <= 0x7E:
                    self._escape = False
                continue
            if byte == 0x1B:
                self._escape = True
                continue
            if byte in (0x0A, 0x0D):
                text = "".join(self._chars).strip()
                self._chars.clear()
                if text:
                    chunks.append(SemanticChunk(kind="user_submit", text=text[-self.max_submit_chars:], payload={"source": "tty_input"}))
                continue
            if byte in (0x7F, 0x08):
                if self._chars:
                    self._chars.pop()
                continue
            if byte < 0x20:
                continue
            char = self._decoder.decode(bytes([byte]), final=False)
            if char:
                self._chars.append(char)
                if len(self._chars) > self.max_submit_chars:
                    self._chars = self._chars[-self.max_submit_chars :]
        return chunks


class SemanticRingBuffer:
    def __init__(self, max_bytes: int = 1024 * 1024) -> None:
        self.max_bytes = max(1, int(max_bytes))
        self._items: deque[SemanticChunk] = deque()
        self._bytes = 0

    @property
    def size_bytes(self) -> int:
        return self._bytes

    def append(self, chunk: SemanticChunk) -> None:
        size = len(chunk.text.encode("utf-8")) + len(chunk.kind) + 64
        self._items.append(chunk)
        self._bytes += size
        while self._items and self._bytes > self.max_bytes:
            old = self._items.popleft()
            self._bytes -= len(old.text.encode("utf-8")) + len(old.kind) + 64

    def items(self) -> list[SemanticChunk]:
        return list(self._items)


class BoundedCleanTerminalLog:
    """Write a cleaned, bounded terminal transcript instead of raw PTY bytes."""

    def __init__(self, path: Path, max_bytes: int) -> None:
        self.path = path
        self.max_bytes = max(1, int(max_bytes))
        self._file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w+b")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.flush()
        if self._file is not None:
            self._file.close()

    def write(self, data: bytes) -> int:
        if self._file is None:
            return 0
        text = data.decode("utf-8", errors="replace")
        cleaned = clean_terminal_text(text, max_chars=None)
        if not cleaned.strip():
            return len(data)
        payload = (cleaned + "\n").encode("utf-8")
        self._file.write(payload)
        self._enforce_limit()
        return len(data)

    def flush(self) -> None:
        if self._file is not None:
            self._file.flush()

    def _enforce_limit(self) -> None:
        if self._file is None:
            return
        size = self._file.tell()
        if size <= self.max_bytes:
            return
        self._file.flush()
        self._file.seek(-self.max_bytes, os.SEEK_END)
        tail = self._file.read(self.max_bytes)
        newline = tail.find(b"\n")
        if newline > 0 and newline + 1 < len(tail):
            tail = tail[newline + 1 :]
        self._file.seek(0)
        self._file.truncate(0)
        self._file.write(tail)
        self._file.seek(0, os.SEEK_END)
