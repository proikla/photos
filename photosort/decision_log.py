"""Human-readable action log for photosort decisions."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TextIO

SEPARATOR = "─" * 40

# Map organizer Action -> short English label for the pretty log
ACTION_LABELS = {
    "moved": "MOVE",
    "copied": "COPY",
    "renamed_and_moved": "RENAME",
    "renamed_and_copied": "RENAME",
    "skipped_duplicate": "SKIP",
    "skipped_already_sorted": "KEEP",
}


def short_hash(h: str | None) -> str:
    """Return first 12 hex chars of a sha256 digest (strip optional sha256=)."""
    if not h:
        return ""
    s = str(h).strip()
    if s.lower().startswith("sha256="):
        s = s[7:]
    # Keep hex only (tolerate uppercase)
    hex_part = "".join(c for c in s if c in "0123456789abcdefABCDEF")
    return hex_part[:12].lower()


def format_action_entry(
    *,
    label: str,
    title: str,
    why: str,
    proof: str,
    from_path: str | Path | None = None,
    to_path: str | Path | None = None,
) -> str:
    """
    Build a multi-line pretty action block:

        MOVE  DSC00197.ARW
          from   /Pictures/misc/DSC00197.ARW
          to     /Pictures/2022/03/DSC00197.ARW
          why    sort into date folder (EXIF)
          proof  sha256=a1b2c3d4e5f6
    """
    lines = [f"{label}  {title}"]
    if from_path is not None:
        lines.append(f"  from   {from_path}")
    if to_path is not None:
        lines.append(f"  to     {to_path}")
    lines.append(f"  why    {why}")
    lines.append(f"  proof  {proof}")
    return "\n".join(lines)


def label_for_action(action: str) -> str:
    return ACTION_LABELS.get(action, action.upper())


class ActionLogger:
    """
    Writes pretty decision blocks to a dedicated human log file and
    mirrors each block via logger.info (so technical photosort.log also
    gets the readable block when file logging is enabled).
    """

    def __init__(
        self,
        path: Path | None = None,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self.path = Path(path) if path is not None else None
        self.logger = logger or logging.getLogger("photosort")
        self._fp: Optional[TextIO] = None
        self._opened = False

    def open(self) -> None:
        if self.path is None or self._opened:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = open(self.path, "a", encoding="utf-8")
        self._opened = True

    def write_header(
        self,
        *,
        mode: str,
        source: Path | str,
        dest: Path | str,
        depth: str = "month",
        dry_run: bool = False,
        when: datetime | None = None,
    ) -> None:
        """Write a run header (separator + mode/source/dest/time)."""
        self.open()
        ts = when or datetime.now(timezone.utc).astimezone()
        # Local wall time without forcing a zone name (portable)
        time_s = ts.strftime("%Y-%m-%d %H:%M:%S %Z").strip() or ts.isoformat(
            timespec="seconds"
        )
        mode_s = mode
        if dry_run and "DRY" not in mode.upper():
            mode_s = f"DRY-RUN {mode}"
        lines = [
            SEPARATOR,
            "photosort actions",
            f"  time    {time_s}",
            f"  mode    {mode_s}",
            f"  depth   {depth}",
            f"  source  {source}",
            f"  dest    {dest}",
            SEPARATOR,
            "",
        ]
        block = "\n".join(lines)
        self._write_raw(block)
        self.logger.info("actions log header\n%s", block.rstrip())

    def log(self, block: str) -> None:
        """Append one formatted action block to file and logger.info."""
        self.open()
        text = block.rstrip() + "\n\n"
        self._write_raw(text)
        # One logger.info call for the whole multi-line block
        self.logger.info("%s", block.rstrip())

    def log_entry(
        self,
        *,
        label: str,
        title: str,
        why: str,
        proof: str,
        from_path: str | Path | None = None,
        to_path: str | Path | None = None,
    ) -> str:
        block = format_action_entry(
            label=label,
            title=title,
            why=why,
            proof=proof,
            from_path=from_path,
            to_path=to_path,
        )
        self.log(block)
        return block

    def write_footer(self, summary: str | None = None) -> None:
        self.open()
        lines = [SEPARATOR]
        if summary:
            lines.append(summary)
            lines.append(SEPARATOR)
        lines.append("")
        self._write_raw("\n".join(lines))

    def close(self) -> None:
        if self._fp is not None:
            try:
                self._fp.flush()
                self._fp.close()
            finally:
                self._fp = None
                self._opened = False

    def _write_raw(self, text: str) -> None:
        if self._fp is not None:
            self._fp.write(text)
            self._fp.flush()

    def __enter__(self) -> "ActionLogger":
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
