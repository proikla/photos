"""Simple stderr progress for long-running scans/copies."""

from __future__ import annotations

import sys
from typing import Optional, TextIO


class Progress:
    """Human-facing progress on stderr. Disabled when quiet=True."""

    def __init__(
        self,
        *,
        quiet: bool = False,
        stream: Optional[TextIO] = None,
        bar_width: int = 28,
    ) -> None:
        self.quiet = quiet
        self.stream = stream or sys.stderr
        self.bar_width = bar_width
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

    def _bar(self, index: int, total: int) -> str:
        if total <= 0:
            return "[" + ("?" * self.bar_width) + "]"
        ratio = min(max(index / total, 0.0), 1.0)
        filled = int(round(ratio * self.bar_width))
        filled = min(filled, self.bar_width)
        empty = self.bar_width - filled
        # Unicode block bar
        return "[" + ("█" * filled) + ("░" * empty) + "]"

    def item(self, index: int, total: int, message: str) -> None:
        if self.quiet:
            return
        pct = int(100 * index / total) if total else 0
        counts = f"{index}/{total}" if total else str(index)
        bar = self._bar(index, total)
        # Keep filename short so the bar stays visible
        name = message
        if len(name) > 40:
            name = "…" + name[-39:]
        line = f"{bar} {pct:3d}%  {counts:>11}  {name}"
        if len(line) > 120:
            line = line[:117] + "..."
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
