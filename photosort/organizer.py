"""Core organize logic: date folders + content-hash duplicate safety."""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal, Optional

from photosort.decision_log import ActionLogger, format_action_entry, label_for_action, short_hash
from photosort.exif_utils import extract_metadata_safe, get_photo_datetime
from photosort.hasher import sha256_file

logger = logging.getLogger("photosort")

IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp",
    ".heic", ".heif", ".bmp", ".gif", ".raw", ".cr2",
    ".nef", ".arw", ".dng", ".orf", ".rw2",
}

# Sidecar extensions photographers expect beside a photo (same basename / stem).
SIDECAR_EXTENSIONS = (".xmp", ".XMP", ".aae", ".AAE")

Depth = Literal["month", "day"]
Action = Literal[
    "copied",
    "moved",
    "skipped_duplicate",
    "skipped_already_sorted",
    "renamed_and_copied",
    "renamed_and_moved",
]


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
    def already_sorted(self) -> int:
        return sum(1 for d in self.decisions if d.action == "skipped_already_sorted")

    @property
    def renamed(self) -> int:
        return sum(1 for d in self.decisions if d.action.startswith("renamed"))


def iter_images(source: Path, recursive: bool = True) -> Iterable[Path]:
    """Yield image files under source. Recursive uses os.walk (all subdirs)."""
    if source.is_file():
        if source.suffix.lower() in IMAGE_EXTENSIONS:
            yield source
        return
    if not source.is_dir():
        return
    if not recursive:
        for name in sorted(os.listdir(source)):
            p = source / name
            if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
                yield p
        return
    # Full tree: every subdirectory, files sorted per directory for stability
    for dirpath, dirnames, filenames in os.walk(source, followlinks=False):
        dirnames.sort()
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if p.suffix.lower() in IMAGE_EXTENSIONS and p.is_file():
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


def find_sidecars(photo: Path) -> list[Path]:
    """
    Sidecar files next to a photo that should travel with it.
    - same stem: IMG_001.xmp beside IMG_001.CR2 / IMG_001.jpg
    - appended: IMG_001.jpg.xmp beside IMG_001.jpg
    """
    found: list[Path] = []
    seen: set[Path] = set()
    parent = photo.parent
    stem = photo.stem
    name = photo.name

    for ext in SIDECAR_EXTENSIONS:
        candidates = (
            parent / f"{stem}{ext}",
            parent / f"{name}{ext}",
        )
        for c in candidates:
            try:
                resolved = c.resolve()
            except OSError:
                resolved = c
            if resolved in seen:
                continue
            if c.is_file():
                seen.add(resolved)
                found.append(c)
    return found


def sidecar_dest_for(src_sidecar: Path, src_photo: Path, dest_photo: Path) -> Path:
    """Map a source sidecar path onto the destination photo's basename."""
    # Appended style: photo.jpg.xmp → dest.jpg.xmp
    if src_sidecar.name.lower().startswith(src_photo.name.lower()) and len(src_sidecar.name) > len(
        src_photo.name
    ):
        extra = src_sidecar.name[len(src_photo.name) :]
        return Path(str(dest_photo) + extra)
    # Same-stem style: photo.xmp → dest.xmp (preserve sidecar suffix casing from source)
    return dest_photo.with_suffix(src_sidecar.suffix)


def transfer_sidecars(
    src_photo: Path,
    dest_photo: Path,
    *,
    move: bool,
    dry_run: bool,
    action_logger: ActionLogger | None = None,
) -> list[tuple[Path, Path]]:
    """Copy or move sidecars alongside the photo. Returns list of (src, dest) pairs."""
    transferred: list[tuple[Path, Path]] = []
    for sc in find_sidecars(src_photo):
        dest_sc = sidecar_dest_for(sc, src_photo, dest_photo)
        if dest_sc.exists():
            # Avoid clobbering an existing sidecar; suffix like photo_1.xmp already
            # matches renamed dest stem. If still colliding, pick unique name.
            dest_sc = unique_dest_path(dest_sc.parent, dest_sc.name)
        label = "MOVE" if move else "COPY"
        why = "sidecar travels with photo"
        if dry_run:
            why = "sidecar travels with photo (dry-run)"
        proof = f"sidecar of {src_photo.name}"
        block = format_action_entry(
            label=label,
            title=f"{sc.name} (sidecar)",
            why=why,
            proof=proof,
            from_path=sc,
            to_path=dest_sc,
        )
        if dry_run:
            transferred.append((sc, dest_sc))
            if action_logger is not None:
                action_logger.log(block)
            else:
                logger.info("%s", block)
            continue
        dest_sc.parent.mkdir(parents=True, exist_ok=True)
        try:
            if move:
                shutil.move(str(sc), str(dest_sc))
            else:
                shutil.copy2(str(sc), str(dest_sc))
            transferred.append((sc, dest_sc))
            if action_logger is not None:
                action_logger.log(block)
            else:
                logger.info("%s", block)
        except OSError as e:
            logger.error("Failed to %s sidecar %s -> %s: %s", "move" if move else "copy", sc, dest_sc, e)
    return transferred


def build_dest_hash_index(
    dest_root: Path,
    *,
    progress: Optional[Any] = None,
) -> dict[str, Path]:
    """Map content hash -> path for images already in dest."""
    index: dict[str, Path] = {}
    if not dest_root.exists():
        return index
    files = list(iter_images(dest_root, recursive=True))
    total = len(files)
    if progress is not None:
        progress.status(f"Indexing {total} existing file(s) in destination…")
    for i, p in enumerate(files, start=1):
        if progress is not None:
            progress.item(i, total, f"hash {p.name}")
        try:
            h = sha256_file(p)
            index[h] = p
        except OSError as e:
            logger.warning("Could not hash existing file %s: %s", p, e)
    if progress is not None:
        progress.done(f"Indexed {len(index)} unique content hash(es) in destination")
    return index


def _same_path(a: Path, b: Path) -> bool:
    """True if a and b refer to the same filesystem object (path or inode)."""
    try:
        if a.resolve() == b.resolve():
            return True
    except OSError:
        pass
    try:
        if a.exists() and b.exists() and a.samefile(b):
            return True
    except OSError:
        pass
    return False


def _record_metadata(
    result: OrganizeResult,
    *,
    src: Path,
    final: Path,
    content_hash: str,
    meta: dict,
) -> None:
    meta = dict(meta)
    meta["source"] = str(src)
    meta["dest"] = str(final)
    meta["path"] = str(final)
    meta["filename"] = final.name
    meta["content_hash"] = content_hash
    result.metadata.append(meta)



def _emit_action(
    action_logger: ActionLogger | None,
    *,
    label: str,
    title: str,
    why: str,
    proof: str,
    from_path: Path | str | None = None,
    to_path: Path | str | None = None,
) -> str:
    """Format + emit one pretty action block (file via ActionLogger and/or logger)."""
    block = format_action_entry(
        label=label,
        title=title,
        why=why,
        proof=proof,
        from_path=from_path,
        to_path=to_path,
    )
    if action_logger is not None:
        action_logger.log(block)
    else:
        logger.info("%s", block)
    return block


def organize(
    source: Path,
    dest: Path | None = None,
    *,
    depth: Depth = "month",
    move: bool = True,
    dry_run: bool = False,
    recursive: bool = True,
    collect_metadata: bool = True,
    progress: Optional[Any] = None,
    action_logger: ActionLogger | None = None,
) -> OrganizeResult:
    """
    Sort images from source into dest date folders with content-hash safety.

    Rules:
    - If dest is omitted, dest = source (in-place sort into YYYY/MM under source).
    - Same content hash already at a *different* path → skip (true duplicate).
    - Same filename, different content → keep both via safe suffix rename.
    - Already at the correct date path → skip (already_sorted); refresh metadata OK.
    - Never overwrite unique files. Default is MOVE; use move=False / --copy to copy.
    - Metadata is ALWAYS extracted from the source path BEFORE move/copy.
    """
    result = OrganizeResult()
    source = source.resolve()
    if dest is None:
        dest = source
    else:
        dest = dest.resolve()
    inplace = source == dest

    if progress is not None:
        progress.phase(f"Scanning source: {source}")
    candidates = []
    for src in iter_images(source, recursive=recursive):
        try:
            # Only skip files already under a *foreign* dest. When inplace,
            # every image under source must be processed.
            if not inplace and (dest in src.parents or src == dest):
                continue
        except (OSError, ValueError) as e:
            logger.debug("Skipping path containment check for %s: %s", src, e)
        candidates.append(src)
    if progress is not None:
        progress.status(f"Found {len(candidates)} image(s) to process")

    if progress is not None:
        progress.phase("Indexing destination")
    existing = build_dest_hash_index(dest, progress=progress)
    result.hashes_before = set(existing.keys())
    # Working index grows as we place files this run
    hash_index: dict[str, Path] = dict(existing)

    if progress is not None:
        mode = "MOVE" if move else "COPY"
        if dry_run:
            mode = f"DRY-RUN {mode}"
        where = "in-place" if inplace else str(dest)
        progress.phase(f"Organizing ({mode}, depth={depth}, dest={where})")

    total = len(candidates)
    for i, src in enumerate(candidates, start=1):
        if progress is not None:
            progress.item(i, total, f"read {src.name}")

        try:
            content_hash = sha256_file(src)
        except OSError as e:
            logger.error("Cannot read %s: %s", src, e)
            continue

        if content_hash in hash_index:
            existing_at = hash_index[content_hash]
            if not _same_path(existing_at, src):
                # True duplicate of another file → skip
                sh = short_hash(content_hash)
                reason = (
                    f"exact duplicate; sha256={sh} already at {existing_at}"
                )
                decision = Decision(
                    source=src,
                    dest=None,
                    action="skipped_duplicate",
                    content_hash=content_hash,
                    reason=reason,
                )
                result.decisions.append(decision)
                _emit_action(
                    action_logger,
                    label="SKIP",
                    title=src.name,
                    why="exact duplicate",
                    proof=f"sha256={sh} already at {existing_at}",
                )
                if progress is not None:
                    progress.item(i, total, f"skip duplicate {src.name}")
                continue
            # else same file (in-place self-hit) → continue to relocate logic

        when = get_photo_datetime(src)
        sub = date_subdir(when, depth)
        dest_dir = dest / sub
        intended = dest_dir / src.name

        # Already at the correct date path (same path or same inode)
        if _same_path(src, intended):
            meta: Optional[dict] = None
            if collect_metadata:
                meta = extract_metadata_safe(src, content_hash=content_hash)
            sh = short_hash(content_hash)
            reason = f"already in correct date folder; sha256={sh}"
            decision = Decision(
                source=src,
                dest=intended,
                action="skipped_already_sorted",
                content_hash=content_hash,
                reason=reason,
            )
            result.decisions.append(decision)
            # Prefer a path relative to dest when possible for the title
            try:
                title = str(intended.relative_to(dest))
            except ValueError:
                title = intended.name
            _emit_action(
                action_logger,
                label="KEEP",
                title=title,
                why="already in correct date folder",
                proof=f"sha256={sh}",
            )
            if progress is not None:
                progress.item(i, total, f"already sorted {src.name}")
            if collect_metadata and meta is not None:
                _record_metadata(
                    result, src=src, final=intended, content_hash=content_hash, meta=meta
                )
            # Keep hash_index pointing at this path
            hash_index[content_hash] = intended
            continue

        conflict_existing_hash: str | None = None
        conflict_path: Path | None = None
        if intended.exists():
            # Name collision but different content (we already know hash differs /
            # not the same inode as src — that case was handled above).
            conflict_path = intended
            try:
                conflict_existing_hash = sha256_file(intended)
            except OSError:
                # Fall back to reverse lookup in the hash index
                for h, p in hash_index.items():
                    if _same_path(p, intended):
                        conflict_existing_hash = h
                        break
            final = unique_dest_path(dest_dir, src.name)
            action: Action = "renamed_and_moved" if move else "renamed_and_copied"
            sh_new = short_hash(content_hash)
            sh_old = short_hash(conflict_existing_hash) if conflict_existing_hash else "?"
            reason = (
                f"name taken by different content; using {final.name}; "
                f"new=sha256={sh_new} existing=sha256={sh_old} at {intended}"
            )
        else:
            final = intended
            action = "moved" if move else "copied"
            sh = short_hash(content_hash)
            reason = f"sort into date folder (EXIF); sha256={sh}"

        # CRITICAL: extract full metadata from SOURCE while it still exists
        # (before move/copy). Never read a vanished source after shutil.move.
        meta = None
        if collect_metadata:
            meta = extract_metadata_safe(src, content_hash=content_hash)

        if not dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)
            try:
                if move:
                    shutil.move(str(src), str(final))
                else:
                    shutil.copy2(str(src), str(final))
            except OSError as e:
                logger.error(
                    "Failed to %s %s -> %s: %s",
                    "move" if move else "copy",
                    src,
                    final,
                    e,
                )
                # Still record whatever metadata we got, with error note
                if collect_metadata and meta is not None:
                    meta = dict(meta)
                    meta["transfer_error"] = str(e)
                    _record_metadata(
                        result, src=src, final=final, content_hash=content_hash, meta=meta
                    )
                continue

            # Sidecars travel with the photo (same basename / appended style)
            transfer_sidecars(
                src, final, move=move, dry_run=False, action_logger=action_logger
            )

            # Optional verification: if pre-move extract was a fallback/error and
            # dest exists, retry from final path (never from vanished source).
            if collect_metadata and meta is not None:
                if meta.get("meta_source") == "fallback" or meta.get("meta_error"):
                    if final.exists():
                        meta = extract_metadata_safe(
                            final,
                            content_hash=content_hash,
                            retry_path=None,
                        )
        else:
            # dry-run: still plan sidecar moves for logging
            transfer_sidecars(
                src, final, move=move, dry_run=True, action_logger=action_logger
            )

        hash_index[content_hash] = final
        decision = Decision(
            source=src,
            dest=final,
            action=action,
            content_hash=content_hash,
            reason=reason,
        )
        result.decisions.append(decision)

        label = label_for_action(action)
        sh = short_hash(content_hash)
        if action.startswith("renamed"):
            title = f"{src.name} → {final.name}"
            why = "name taken by different content"
            sh_old = short_hash(conflict_existing_hash) if conflict_existing_hash else "?"
            proof = (
                f"new=sha256={sh}  existing=sha256={sh_old} at {conflict_path or intended}"
            )
        else:
            title = src.name
            why = "sort into date folder (EXIF)"
            if dry_run:
                why = "sort into date folder (EXIF, dry-run)"
            proof = f"sha256={sh}"
        _emit_action(
            action_logger,
            label=label,
            title=title,
            why=why,
            proof=proof,
            from_path=src,
            to_path=final if not dry_run else f"(dry-run) {final}",
        )
        if progress is not None:
            dest_show = final if not dry_run else f"(dry-run) {final}"
            progress.item(i, total, f"{action} {src.name} -> {dest_show}")

        if collect_metadata and meta is not None:
            _record_metadata(
                result, src=src, final=final, content_hash=content_hash, meta=meta
            )

    # Inventory after: hashes present in dest (re-scan if not dry-run)
    if dry_run:
        result.hashes_after = set(result.hashes_before) | {
            d.content_hash
            for d in result.decisions
            if d.action not in ("skipped_duplicate", "skipped_already_sorted")
        }
        # already_sorted hashes were already in hashes_before; for dry-run
        # moves/copies we union newly placed. Inplace dry-run: before == after.
        if inplace:
            result.hashes_after = set(result.hashes_before)
    else:
        if progress is not None:
            progress.phase("Verifying destination inventory")
        result.hashes_after = set(build_dest_hash_index(dest, progress=progress).keys())

    if progress is not None:
        progress.done(
            f"Done: copied/moved={result.copied + result.moved} "
            f"renamed={result.renamed} skipped_dup={result.skipped} "
            f"already_sorted={result.already_sorted}"
        )

    return result
