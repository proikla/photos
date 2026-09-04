"""Core organize logic: date folders + content-hash duplicate safety."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal, Optional

from photosort.exif_utils import extract_metadata, get_photo_datetime
from photosort.hasher import sha256_file

logger = logging.getLogger("photosort")

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp",
    ".heic", ".heif", ".bmp", ".gif", ".raw", ".cr2",
    ".nef", ".arw", ".dng", ".orf", ".rw2",
}

Depth = Literal["month", "day"]
Action = Literal["copied", "moved", "skipped_duplicate", "renamed_and_copied", "renamed_and_moved"]


@dataclass
class Decision:
    source: Path
    dest: Optional[Path]
    action: Action
    content_hash: str
    reason: str


@dataclass
class OrganizeResult:
    decisions: list[Decision] = field(default_factory=list)
    metadata: list[dict] = field(default_factory=list)
    hashes_before: set[str] = field(default_factory=set)
    hashes_after: set[str] = field(default_factory=set)

    @property
    def copied(self) -> int:
        return sum(1 for d in self.decisions if d.action in ("copied", "renamed_and_copied"))

    @property
    def moved(self) -> int:
        return sum(1 for d in self.decisions if d.action in ("moved", "renamed_and_moved"))

    @property
    def skipped(self) -> int:
        return sum(1 for d in self.decisions if d.action == "skipped_duplicate")

    @property
    def renamed(self) -> int:
        return sum(1 for d in self.decisions if d.action.startswith("renamed"))


def iter_images(source: Path, recursive: bool = True) -> Iterable[Path]:
    if source.is_file():
        if source.suffix.lower() in IMAGE_EXTENSIONS:
            yield source
        return
    pattern = "**/*" if recursive else "*"
    for p in sorted(source.glob(pattern)):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
            yield p


def date_subdir(when, depth: Depth) -> Path:
    if depth == "day":
        return Path(f"{when.year:04d}") / f"{when.month:02d}" / f"{when.day:02d}"
    return Path(f"{when.year:04d}") / f"{when.month:02d}"


def unique_dest_path(dest_dir: Path, filename: str) -> Path:
    """
    Pick a non-colliding path under dest_dir.
    If `filename` exists, try stem_1.ext, stem_2.ext, ...
    """
    candidate = dest_dir / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    n = 1
    while True:
        candidate = dest_dir / f"{stem}_{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def build_dest_hash_index(dest_root: Path) -> dict[str, Path]:
    """Map content hash -> path for images already in dest."""
    index: dict[str, Path] = {}
    if not dest_root.exists():
        return index
    for p in iter_images(dest_root, recursive=True):
        try:
            h = sha256_file(p)
            index[h] = p
        except OSError as e:
            logger.warning("Could not hash existing file %s: %s", p, e)
    return index


def organize(
    source: Path,
    dest: Path,
    *,
    depth: Depth = "month",
    move: bool = False,
    dry_run: bool = False,
    recursive: bool = True,
    collect_metadata: bool = True,
) -> OrganizeResult:
    """
    Sort images from source into dest date folders with content-hash safety.

    Rules:
    - Same content hash already in dest → skip (true duplicate).
    - Same filename, different content → keep both via safe suffix rename.
    - Never overwrite unique files. Default is COPY; MOVE only if move=True.
    """
    result = OrganizeResult()
    source = source.resolve()
    dest = dest.resolve()

    existing = build_dest_hash_index(dest)
    result.hashes_before = set(existing.keys())
    # Working index grows as we place files this run
    hash_index: dict[str, Path] = dict(existing)
    # Also track hashes of sources we've already placed this run
    # (in case source itself has internal duplicates)

    for src in iter_images(source, recursive=recursive):
        # Skip files already under dest (avoid re-copying when source==dest subtree)
        try:
            if dest in src.parents or src == dest:
                continue
        except Exception:
            pass

        try:
            content_hash = sha256_file(src)
        except OSError as e:
            logger.error("Cannot read %s: %s", src, e)
            continue

        if content_hash in hash_index:
            decision = Decision(
                source=src,
                dest=None,
                action="skipped_duplicate",
                content_hash=content_hash,
                reason=f"identical content already at {hash_index[content_hash]}",
            )
            result.decisions.append(decision)
            logger.info("SKIP duplicate %s (== %s)", src, hash_index[content_hash])
            continue

        when = get_photo_datetime(src)
        sub = date_subdir(when, depth)
        dest_dir = dest / sub
        intended = dest_dir / src.name

        if intended.exists():
            # Name collision but different content (we already know hash differs)
            final = unique_dest_path(dest_dir, src.name)
            action: Action = "renamed_and_moved" if move else "renamed_and_copied"
            reason = f"name conflict with different content; using {final.name}"
        else:
            final = intended
            action = "moved" if move else "copied"
            reason = "ok"

        if not dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)
            if move:
                shutil.move(str(src), str(final))
            else:
                shutil.copy2(str(src), str(final))

        hash_index[content_hash] = final
        decision = Decision(
            source=src,
            dest=final,
            action=action,
            content_hash=content_hash,
            reason=reason,
        )
        result.decisions.append(decision)
        logger.info(
            "%s %s -> %s (%s)",
            action.upper(),
            src,
            final if not dry_run else f"(dry-run) {final}",
            reason,
        )

        if collect_metadata:
            try:
                meta = extract_metadata(final if not dry_run and not move else src)
                # Prefer original source path for provenance; store dest too
                meta["source"] = str(src)
                meta["dest"] = str(final)
                meta["content_hash"] = content_hash
                result.metadata.append(meta)
            except Exception as e:
                logger.warning("Metadata extract failed for %s: %s", src, e)

    # Inventory after: hashes present in dest (re-scan if not dry-run)
    if dry_run:
        result.hashes_after = set(result.hashes_before) | {
            d.content_hash
            for d in result.decisions
            if d.action != "skipped_duplicate"
        }
    else:
        result.hashes_after = set(build_dest_hash_index(dest).keys())

    return result
