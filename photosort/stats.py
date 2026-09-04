"""Aggregate lens / focal-length stats from metadata records."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from photosort.metadata_store import load_metadata

logger = logging.getLogger("photosort")


def most_used_lenses(records: list[dict[str, Any]], top: int = 10) -> list[tuple[str, int]]:
    c: Counter[str] = Counter()
    for r in records:
        lens = r.get("lens")
        if lens:
            c[str(lens)] += 1
    return c.most_common(top)


def most_used_focal_lengths(
    records: list[dict[str, Any]],
    *,
    lens: Optional[str] = None,
    top: int = 20,
) -> list[tuple[Any, int]]:
    c: Counter[Any] = Counter()
    for r in records:
        if lens is not None and r.get("lens") != lens:
            continue
        fl = r.get("focal_length_mm")
        if fl is not None:
            c[fl] += 1
    return c.most_common(top)


def focal_length_histogram(
    records: list[dict[str, Any]],
    *,
    lens: Optional[str] = None,
) -> list[tuple[float, int]]:
    """All focal lengths sorted ascending (min → max) with photo counts."""
    c: Counter[float] = Counter()
    for r in records:
        if lens is not None and r.get("lens") != lens:
            continue
        fl = r.get("focal_length_mm")
        if fl is None:
            continue
        try:
            c[float(fl)] += 1
        except (TypeError, ValueError):
            continue
    return sorted(c.items(), key=lambda x: x[0])


def coverage(records: list[dict[str, Any]]) -> dict[str, int]:
    """How many records have each kind of EXIF field."""
    total = len(records)
    with_lens = sum(1 for r in records if r.get("lens"))
    with_focal = sum(1 for r in records if r.get("focal_length_mm") is not None)
    with_camera = sum(1 for r in records if r.get("camera"))
    with_aperture = sum(1 for r in records if r.get("aperture"))
    return {
        "total": total,
        "with_lens": with_lens,
        "without_lens": total - with_lens,
        "with_focal": with_focal,
        "without_focal": total - with_focal,
        "with_camera": with_camera,
        "with_aperture": with_aperture,
    }


def format_stats(records: list[dict[str, Any]], lens_filter: Optional[str] = None) -> str:
    cov = coverage(records)
    lines: list[str] = []
    lines.append(f"Photos scanned: {cov['total']}")
    lines.append("EXIF coverage:")
    lines.append(
        f"  lens model:     {cov['with_lens']:5d}  "
        f"({cov['without_lens']} without / unknown)"
    )
    lines.append(
        f"  focal length:   {cov['with_focal']:5d}  "
        f"({cov['without_focal']} without / unknown)"
    )
    lines.append(f"  camera:         {cov['with_camera']:5d}")
    lines.append(f"  aperture:       {cov['with_aperture']:5d}")
    lines.append("")
    lines.append(
        "Most-used lenses "
        f"(among {cov['with_lens']} photos that have LensModel in EXIF):"
    )
    lenses = most_used_lenses(records)
    for name, count in lenses:
        lines.append(f"  {count:5d}  {name}")
    if not lenses:
        lines.append("  (none)")
    if cov["without_lens"]:
        lines.append(
            f"  {cov['without_lens']:5d}  (no lens EXIF — phone/screenshot/edited/RAW without tag)"
        )
    lines.append("")
    title = "Most-used focal lengths"
    if lens_filter:
        title += f" (lens={lens_filter})"
    else:
        title += f" (among {cov['with_focal']} photos with focal length)"
    lines.append(title + ":")
    fls = most_used_focal_lengths(records, lens=lens_filter)
    for fl, count in fls:
        lines.append(f"  {count:5d}  {fl} mm")
    if not fls:
        lines.append("  (none)")
    if not lens_filter and cov["without_focal"]:
        lines.append(
            f"  {cov['without_focal']:5d}  (no focal length EXIF)"
        )
    return "\n".join(lines) + "\n"


def matplotlib_available() -> bool:
    try:
        import matplotlib  # noqa: F401
        return True
    except ImportError:
        return False


def plot_focal_lengths(
    records: list[dict[str, Any]],
    out_path: Path,
    *,
    lens: Optional[str] = None,
) -> bool:
    """
    Bar chart: X = focal length (mm) from min→max, Y = photo count.
    Returns False if matplotlib missing or no focal data.
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    data = focal_length_histogram(records, lens=lens)
    if not data:
        return False

    focals = [x[0] for x in data]
    counts = [x[1] for x in data]
    # Width scales a bit with number of distinct focals
    width = max(10.0, min(24.0, 0.35 * len(focals) + 4))
    fig, ax = plt.subplots(figsize=(width, 5))
    labels = [str(int(f)) if float(f).is_integer() else str(f) for f in focals]
    ax.bar(labels, counts, color="#4C78A8", edgecolor="white", linewidth=0.4)
    ax.set_xlabel("Focal length (mm)")
    ax.set_ylabel("Photos")
    title = "Focal length usage (min → max)"
    if lens:
        title += f" — {lens}"
    ax.set_title(title)
    ax.set_ylim(bottom=0)
    # Avoid unreadable ticks when many distinct focals
    if len(labels) > 40:
        step = max(1, len(labels) // 30)
        for i, tick in enumerate(ax.get_xticklabels()):
            tick.set_visible(i % step == 0)
    plt.xticks(rotation=45, ha="right")
    fig.tight_layout()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return out_path.is_file()


# Back-compat alias
def maybe_plot_focal_lengths(
    records: list[dict[str, Any]],
    out_path: Path,
    *,
    lens: Optional[str] = None,
) -> bool:
    return plot_focal_lengths(records, out_path, lens=lens)


def open_with_default_app(path: Path) -> bool:
    """Open a file with the OS default application (image viewer)."""
    path = Path(path).resolve()
    if not path.is_file():
        return False
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)], start_new_session=True)
            return True
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
            return True
        opener = shutil.which("xdg-open") or shutil.which("gio")
        if opener:
            cmd = [opener, str(path)] if "xdg-open" in opener else [opener, "open", str(path)]
            subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    except OSError as e:
        logger.warning("Could not open %s: %s", path, e)
    return False


def prompt_yes_no(message: str, *, default_yes: bool = True) -> bool:
    """Interactive Y/n. default_yes=True → empty Enter means yes."""
    suffix = " [Y/n] " if default_yes else " [y/N] "
    try:
        raw = input(message + suffix)
    except EOFError:
        return default_yes
    ans = raw.strip().lower()
    if not ans:
        return default_yes
    return ans in {"y", "yes", "д", "да"}


def stats_from_file(meta_path: Path, lens_filter: Optional[str] = None) -> str:
    return format_stats(load_metadata(meta_path), lens_filter=lens_filter)
