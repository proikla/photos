"""Aggregate lens / focal-length stats from metadata records."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Optional

from photosort.metadata_store import load_metadata


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


def maybe_plot_focal_lengths(
    records: list[dict[str, Any]],
    out_path: Path,
    *,
    lens: Optional[str] = None,
) -> bool:
    """Optional matplotlib chart. Returns False if matplotlib unavailable."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    data = most_used_focal_lengths(records, lens=lens, top=30)
    if not data:
        return False
    labels = [str(x[0]) for x in data]
    values = [x[1] for x in data]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(labels, values)
    ax.set_xlabel("Focal length (mm)")
    ax.set_ylabel("Count")
    title = "Focal length usage"
    if lens:
        title += f" — {lens}"
    ax.set_title(title)
    plt.xticks(rotation=45, ha="right")
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    return True


def stats_from_file(meta_path: Path, lens_filter: Optional[str] = None) -> str:
    return format_stats(load_metadata(meta_path), lens_filter=lens_filter)
