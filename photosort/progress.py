"""Simple stderr progress for long-running scans/copies."""

from __future__ import annotations

import sys
from typing import Optional, TextIO


class Progress:
    """Human-facing progress on stderr. Disabled when quiet=True."""

    def __init__(self, *, quiet: bool = False, stream: Optional[TextIO] = None) -> None:
        self.quiet = quiet
        self.stream = stream or sys.stderr
        self._last_len = 0
        self._live = False

    def phase(self, message: str) -> None:
        if self.quiet:
            return
        self._finish_line()
        print(f"==> {message}", file=self.stream, flush=True)

    def status(self, message: str) -> None:
        if self.quiet:
            return
        self._finish_line()
        print(message, file=self.stream, flush=True)

    def item(self, index: int, total: int, message: str) -> None:
        if self.quiet:
            return
        # Keep one live updating line
        prefix = f"[{index}/{total}] " if total else f"[{index}] "
        line = prefix + message
        # Truncate to keep terminal readable
        if len(line) > 100:
            line = line[:97] + "..."
        pad = max(0, self._last_len - len(line))
        print("\r" + line + (" " * pad), end="", file=self.stream, flush=True)
        self._last_len = len(line)
        self._live = True

    def done(self, message: Optional[str] = None) -> None:
        if self.quiet:
            return
        self._finish_line()
        if message:
            print(message, file=self.stream, flush=True)

    def _finish_line(self) -> None:
        if self._live:
            print(file=self.stream, flush=True)
            self._live = False
            self._last_len = 0
