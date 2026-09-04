"""Simple JSON metadata inventory + live scan from a photo tree."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from photosort.exif_utils import extract_metadata
from photosort.hasher import sha256_file
from photosort.organizer import iter_images


DEFAULT_METADATA_NAME = "photosort_metadata.json"


def save_metadata(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_metadata(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def scan_photos_for_metadata(
    root: Path,
    *,
    recursive: bool = True,
    progress: Optional[Any] = None,
) -> list[dict[str, Any]]:
    """Walk ALL image files under root (recursive by default) and extract EXIF."""
    import os

    root = root.resolve()
    if progress is not None:
        progress.phase(f"Walking directories under {root}")

    files = list(iter_images(root, recursive=recursive))
    dir_count = (
        sum(1 for _ in os.walk(root, followlinks=False))
        if root.is_dir() and recursive
        else (1 if root.is_dir() else 0)
    )

    total = len(files)
    if progress is not None:
        noun = "directory" if dir_count == 1 else "directories"
        progress.status(f"Found {total} image(s) across {dir_count} {noun}")
        progress.phase(f"Reading EXIF ({total} file(s))")

    records: list[dict[str, Any]] = []
    for i, path in enumerate(files, start=1):
        # Show relative path so deep folders are visible on the bar
        try:
            label = str(path.relative_to(root))
        except ValueError:
            label = path.name
        if progress is not None:
            progress.item(i, total, label)
        try:
            meta = extract_metadata(path)
            try:
                meta["content_hash"] = sha256_file(path)
            except OSError:
                meta["content_hash"] = None
            meta["source"] = str(path)
            meta["dest"] = str(path)
            records.append(meta)
        except Exception:
            continue
    if progress is not None:
        progress.done(f"Scanned {len(records)} image(s) from full tree")
    return records


def resolve_metadata_records(
    path: Path,
    *,
    rescan: bool = False,
    use_cache: bool = False,
    recursive: bool = True,
    progress: Optional[Any] = None,
) -> tuple[list[dict[str, Any]], str]:
    """
    Load stats records from a JSON file or a photo directory.

    For a directory, walks ALL subdirectories by default (live EXIF scan).
    Pass use_cache=True to read DIR/photosort_metadata.json instead.
    rescan is kept as an alias that forces a live scan (overrides use_cache).

    Returns (records, source_description).
    """
    path = path.expanduser()
    if not path.exists():
        raise FileNotFoundError(f"path not found: {path}")

    if path.is_file():
        if path.suffix.lower() == ".json":
            if progress is not None:
                progress.phase(f"Loading metadata JSON: {path}")
            return load_metadata(path), f"json:{path}"
        # Single image file
        meta = extract_metadata(path)
        try:
            meta["content_hash"] = sha256_file(path)
        except OSError:
            meta["content_hash"] = None
        meta["source"] = str(path)
        meta["dest"] = str(path)
        return [meta], f"scan:{path}"

    # Directory: full tree scan by default (do not silently trust partial JSON)
    cached = path / DEFAULT_METADATA_NAME
    if use_cache and not rescan and cached.is_file():
        if progress is not None:
            progress.phase(f"Loading cached metadata: {cached}")
        records = load_metadata(cached)
        if records:
            if progress is not None:
                progress.done(
                    f"Loaded {len(records)} record(s) from cache "
                    f"(pass without --cache / with --rescan to walk all folders)"
                )
            return records, f"json:{cached}"
        if progress is not None:
            progress.status("Cache empty — walking full tree")

    records = scan_photos_for_metadata(path, recursive=recursive, progress=progress)
    return records, f"scan:{path}"
