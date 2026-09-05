"""EXIF / RAW metadata: prefer ExifTool (lens tags on RAW), fall back to Pillow."""

from __future__ import annotations

import datetime as dt
import json
import logging
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ExifTags

logger = logging.getLogger("photosort")

# Map tag names we care about (Pillow path)
_TAG_NAME_TO_ID = {v: k for k, v in ExifTags.TAGS.items()}
_DATETIME_ORIGINAL = _TAG_NAME_TO_ID.get("DateTimeOriginal")
_DATETIME = _TAG_NAME_TO_ID.get("DateTime")
_MAKE = _TAG_NAME_TO_ID.get("Make")
_MODEL = _TAG_NAME_TO_ID.get("Model")
_LENS_MODEL = _TAG_NAME_TO_ID.get("LensModel")
_FNUMBER = _TAG_NAME_TO_ID.get("FNumber")
_FOCAL_LENGTH = _TAG_NAME_TO_ID.get("FocalLength")
_EXPOSURE_TIME = _TAG_NAME_TO_ID.get("ExposureTime")
_ISO = _TAG_NAME_TO_ID.get("ISOSpeedRatings") or _TAG_NAME_TO_ID.get("PhotographicSensitivity")

RAW_EXTENSIONS = {
    ".raw", ".cr2", ".cr3", ".nef", ".nrw", ".arw", ".srf", ".sr2",
    ".dng", ".orf", ".rw2", ".pef", ".ptx", ".raf", ".3fr", ".fff",
    ".iiq", ".rwl", ".srw", ".x3f", ".mrw",
}

# ExifTool tags we always want parsed into summary fields.
# Full dump still comes back because we also request -All (see _run_exiftool_json).
_EXIFTOOL_TAGS = [
    "-DateTimeOriginal",
    "-CreateDate",
    "-ModifyDate",
    "-Make",
    "-Model",
    "-LensModel",
    "-Lens",
    "-LensID",
    "-LensType",
    "-FocalLength",
    "-FocalLengthIn35mmFormat",
    "-FNumber",
    "-Aperture",
    "-ExposureTime",
    "-ShutterSpeed",
    "-ISO",
    "-FileName",
    "-SourceFile",
]


@lru_cache(maxsize=1)
def exiftool_path() -> Optional[str]:
    return shutil.which("exiftool")


def exiftool_available() -> bool:
    return exiftool_path() is not None


def _rational_to_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if hasattr(val, "numerator") and hasattr(val, "denominator"):
        den = val.denominator
        return float(val.numerator) / float(den) if den else None
    if isinstance(val, tuple) and len(val) == 2:
        num, den = val
        return float(num) / float(den) if den else None
    if isinstance(val, str):
        s = val.strip().lower().replace("mm", "").strip()
        # exiftool without -n sometimes returns "35.0 mm" or "1/125"
        if "/" in s and not s.startswith("f"):
            try:
                a, b = s.split("/", 1)
                return float(a) / float(b) if float(b) else None
            except ValueError:
                pass
        try:
            return float(s)
        except ValueError:
            return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _format_shutter(seconds: Optional[float]) -> Optional[str]:
    if seconds is None:
        return None
    if seconds >= 1:
        return f"{seconds:g}s"
    if seconds > 0:
        denom = round(1 / seconds)
        return f"1/{denom}"
    return None


def _parse_exif_datetime(raw: Any) -> Optional[dt.datetime]:
    if not raw:
        return None
    s = raw if isinstance(raw, str) else (
        raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    )
    s = s.strip()
    # ExifTool may use "+00:00" or "Z"
    if s.endswith("Z"):
        s = s[:-1]
    if len(s) >= 6 and (s[-6] in "+-") and s[-3] == ":":
        s = s[:-6].strip()
    for fmt in (
        "%Y:%m:%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y:%m:%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _jsonable(val: Any) -> Any:
    """Make a value JSON-serializable for metadata inventory."""
    if val is None or isinstance(val, (bool, int, float, str)):
        return val
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    if isinstance(val, (list, tuple)):
        return [_jsonable(v) for v in val]
    if isinstance(val, dict):
        return {str(k): _jsonable(v) for k, v in val.items()}
    if hasattr(val, "numerator") and hasattr(val, "denominator"):
        den = val.denominator
        return float(val.numerator) / float(den) if den else None
    try:
        json.dumps(val)
        return val
    except (TypeError, ValueError):
        return str(val)


def _empty_meta(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "filename": path.name,
        "datetime": None,
        "camera": None,
        "lens": None,
        "aperture": None,
        "focal_length_mm": None,
        "shutter": None,
        "iso": None,
        "meta_source": None,
        "exif": {},
    }


def fallback_metadata(
    path: Path,
    *,
    error: Optional[str] = None,
    content_hash: Optional[str] = None,
) -> dict[str, Any]:
    """
    Minimal record when full EXIF extract fails.
    Never silently drop a placed file from the inventory.
    """
    meta = _empty_meta(path)
    meta["meta_source"] = "fallback"
    if error:
        meta["meta_error"] = str(error)
    if content_hash is not None:
        meta["content_hash"] = content_hash
    try:
        if path.exists():
            meta["datetime"] = dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat(sep=" ")
    except OSError as e:
        meta["meta_error"] = (
            f"{meta.get('meta_error') + '; ' if meta.get('meta_error') else ''}"
            f"mtime unavailable: {e}"
        )
    return meta


def _pick_lens(data: dict[str, Any]) -> Optional[str]:
    for key in ("LensModel", "Lens", "LensID", "LensType"):
        val = data.get(key)
        if val is None:
            continue
        s = str(val).strip()
        if not s or s.lower() in {"unknown", "none", "n/a"}:
            continue
        # Skip pure numeric LensID when a better name may appear later — still use if only option
        return s
    return None


def _meta_from_exiftool_dict(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    meta = _empty_meta(path)
    meta["meta_source"] = "exiftool"
    # Keep richer dump so we do not throw away tags
    meta["exif"] = {str(k): _jsonable(v) for k, v in data.items()}

    when = None
    for key in ("DateTimeOriginal", "CreateDate", "ModifyDate"):
        when = _parse_exif_datetime(data.get(key))
        if when is not None:
            break
    if when is None:
        try:
            when = dt.datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            when = None
    meta["datetime"] = when.isoformat(sep=" ") if when else None

    make = data.get("Make")
    model = data.get("Model")
    parts = [str(p).strip() for p in (make, model) if p and str(p).strip()]
    meta["camera"] = " ".join(parts) if parts else None

    meta["lens"] = _pick_lens(data)

    fnum = _rational_to_float(data.get("FNumber"))
    if fnum is None:
        fnum = _rational_to_float(data.get("Aperture"))
    if fnum is not None:
        meta["aperture"] = f"f/{fnum:g}"

    focal = _rational_to_float(data.get("FocalLength"))
    if focal is None:
        focal = _rational_to_float(data.get("FocalLengthIn35mmFormat"))
    if focal is not None:
        meta["focal_length_mm"] = round(focal, 1) if focal != int(focal) else int(focal)

    exposure = _rational_to_float(data.get("ExposureTime"))
    if exposure is None:
        exposure = _rational_to_float(data.get("ShutterSpeed"))
    meta["shutter"] = _format_shutter(exposure)

    iso_val = data.get("ISO")
    if isinstance(iso_val, (tuple, list)) and iso_val:
        iso_val = iso_val[0]
    if iso_val is not None:
        try:
            meta["iso"] = int(float(iso_val))
        except (TypeError, ValueError):
            pass

    return meta


def _run_exiftool_json(paths: list[Path]) -> list[dict[str, Any]]:
    """
    Run exiftool -json -n on paths; return list of tag dicts (may be shorter on errors).
    Requests -All so the richer dump is available under meta['exif'].
    """
    exe = exiftool_path()
    if not exe or not paths:
        return []
    cmd = [
        exe,
        "-json",
        "-n",
        "-q",
        "-q",
        "-All",
        *_EXIFTOOL_TAGS,
        "--",
        *[str(p) for p in paths],
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=max(120, 2 * len(paths)),
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("exiftool failed: %s", e)
        return []
    out = (proc.stdout or "").strip()
    if not out:
        if proc.returncode not in (0, None):
            err = (proc.stderr or "").strip()
            logger.warning(
                "exiftool returned no JSON for %d path(s) (rc=%s): %s",
                len(paths),
                proc.returncode,
                err[:500] if err else "(no stderr)",
            )
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        logger.warning("exiftool returned invalid JSON")
        return []
    if not isinstance(data, list):
        return []
    return data


def extract_metadata_exiftool(path: Path) -> Optional[dict[str, Any]]:
    rows = _run_exiftool_json([path])
    if not rows:
        return None
    return _meta_from_exiftool_dict(path, rows[0])


def extract_metadata_batch_exiftool(
    paths: list[Path],
    *,
    chunk_size: int = 200,
    progress: Any = None,
) -> dict[str, dict[str, Any]]:
    """
    Batch-read metadata with ExifTool.
    Returns map of resolved path str -> meta dict.
    Files missing from exiftool output are omitted (caller should fall back).
    """
    result: dict[str, dict[str, Any]] = {}
    if not paths or not exiftool_available():
        return result

    total = len(paths)
    done = 0
    for start in range(0, total, chunk_size):
        chunk = paths[start : start + chunk_size]
        rows = _run_exiftool_json(chunk)
        # Map by SourceFile when present
        by_source: dict[str, dict[str, Any]] = {}
        for row in rows:
            src = row.get("SourceFile")
            if src:
                try:
                    by_source[str(Path(src).resolve())] = row
                except OSError:
                    pass
                by_source[str(Path(src))] = row

        missing: list[Path] = []
        for p in chunk:
            done += 1
            if progress is not None:
                try:
                    label = p.name
                    progress.item(done, total, label)
                except Exception:
                    pass
            key = str(p.resolve())
            row = by_source.get(key) or by_source.get(str(p))
            if row is None:
                # try match by filename only as last resort within chunk
                for r in rows:
                    if Path(str(r.get("SourceFile", ""))).name == p.name:
                        row = r
                        break
            if row is not None:
                result[key] = _meta_from_exiftool_dict(p, row)
            else:
                missing.append(p)
        if missing:
            logger.warning(
                "exiftool batch missed %d/%d file(s) in chunk; callers should fall back",
                len(missing),
                len(chunk),
            )
    return result


def _get_exif_dict(img: Image.Image) -> dict:
    result: dict = {}
    try:
        exif = img.getexif()
    except Exception:
        return result
    if not exif:
        return result
    for k, v in exif.items():
        result[k] = v
    try:
        ifd = exif.get_ifd(0x8769)
        for k, v in ifd.items():
            result[k] = v
    except Exception:
        pass
    return result


def _pillow_exif_named(exif: dict) -> dict[str, Any]:
    """Named, JSON-safe dump of Pillow EXIF for meta['exif']."""
    named: dict[str, Any] = {}
    for tag_id, val in exif.items():
        name = ExifTags.TAGS.get(tag_id, str(tag_id))
        named[name] = _jsonable(val)
    return named


def _extract_via_pillow(path: Path) -> dict[str, Any]:
    meta = _empty_meta(path)
    meta["meta_source"] = "pillow"

    when = None
    exif: dict = {}
    try:
        with Image.open(path) as img:
            exif = _get_exif_dict(img)
            for tag_id in (_DATETIME_ORIGINAL, _DATETIME):
                if tag_id is None:
                    continue
                when = _parse_exif_datetime(exif.get(tag_id))
                if when is not None:
                    break
    except Exception as e:
        logger.debug("Pillow open/exif failed for %s: %s", path, e)
        exif = {}

    if when is None:
        try:
            when = dt.datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            when = None
    meta["datetime"] = when.isoformat(sep=" ") if when else None

    if exif:
        meta["exif"] = _pillow_exif_named(exif)

    if not exif:
        return meta

    make = exif.get(_MAKE) if _MAKE else None
    model = exif.get(_MODEL) if _MODEL else None
    if isinstance(make, bytes):
        make = make.decode("utf-8", errors="replace")
    if isinstance(model, bytes):
        model = model.decode("utf-8", errors="replace")
    if make or model:
        parts = [p.strip() for p in (make or "", model or "") if p and str(p).strip()]
        meta["camera"] = " ".join(parts) if parts else None

    lens = exif.get(_LENS_MODEL) if _LENS_MODEL else None
    if isinstance(lens, bytes):
        lens = lens.decode("utf-8", errors="replace")
    if lens:
        meta["lens"] = str(lens).strip()

    fnum = _rational_to_float(exif.get(_FNUMBER)) if _FNUMBER else None
    if fnum is not None:
        meta["aperture"] = f"f/{fnum:g}"

    focal = _rational_to_float(exif.get(_FOCAL_LENGTH)) if _FOCAL_LENGTH else None
    if focal is not None:
        meta["focal_length_mm"] = round(focal, 1) if focal != int(focal) else int(focal)

    exposure = _rational_to_float(exif.get(_EXPOSURE_TIME)) if _EXPOSURE_TIME else None
    meta["shutter"] = _format_shutter(exposure)

    iso_val = exif.get(_ISO) if _ISO else None
    if isinstance(iso_val, (tuple, list)) and iso_val:
        iso_val = iso_val[0]
    if iso_val is not None:
        try:
            meta["iso"] = int(iso_val)
        except (TypeError, ValueError):
            pass

    return meta


def get_photo_datetime(path: Path) -> dt.datetime:
    """
    Date priority: EXIF DateTimeOriginal → CreateDate/DateTime → file mtime.
    Uses ExifTool for RAW (and whenever available), else Pillow.
    """
    suffix = path.suffix.lower()
    if exiftool_available() and suffix in RAW_EXTENSIONS:
        rows = _run_exiftool_json([path])
        if rows:
            for key in ("DateTimeOriginal", "CreateDate", "ModifyDate"):
                parsed = _parse_exif_datetime(rows[0].get(key))
                if parsed is not None:
                    return parsed

    try:
        with Image.open(path) as img:
            exif = _get_exif_dict(img)
            for tag_id in (_DATETIME_ORIGINAL, _DATETIME):
                if tag_id is None:
                    continue
                parsed = _parse_exif_datetime(exif.get(tag_id))
                if parsed is not None:
                    return parsed
    except Exception:
        pass

    if exiftool_available():
        rows = _run_exiftool_json([path])
        if rows:
            for key in ("DateTimeOriginal", "CreateDate", "ModifyDate"):
                parsed = _parse_exif_datetime(rows[0].get(key))
                if parsed is not None:
                    return parsed

    return dt.datetime.fromtimestamp(path.stat().st_mtime)


def extract_metadata(path: Path) -> dict[str, Any]:
    """
    Collect camera metadata. Prefer ExifTool (reads lens tags on RAW the way
    Lightroom/Capture One do); fall back to Pillow for JPEG/PNG when needed.
    Raises OSError if path cannot be read at all; callers may use fallback_metadata.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No such file or directory: {path}")
    suffix = path.suffix.lower()

    # Always try ExifTool first when installed — critical for RAW lens/focal
    if exiftool_available():
        meta = extract_metadata_exiftool(path)
        if meta is not None:
            # If JPEG somehow missing lens but Pillow might have it, merge
            if meta.get("lens") or suffix in RAW_EXTENSIONS:
                return meta
            pillow = _extract_via_pillow(path)
            for key in ("lens", "focal_length_mm", "aperture", "shutter", "iso", "camera"):
                if meta.get(key) is None and pillow.get(key) is not None:
                    meta[key] = pillow[key]
            # Merge pillow exif dump if exiftool dump is thin
            if pillow.get("exif") and not meta.get("exif"):
                meta["exif"] = pillow["exif"]
            elif pillow.get("exif"):
                for k, v in pillow["exif"].items():
                    meta["exif"].setdefault(k, v)
            return meta

    return _extract_via_pillow(path)


def extract_metadata_safe(
    path: Path,
    *,
    content_hash: Optional[str] = None,
    retry_path: Optional[Path] = None,
) -> dict[str, Any]:
    """
    Extract metadata without raising. On failure, retry from retry_path if it
    exists, then fall back to a minimal path/hash/datetime record (never silent drop).
    """
    path = Path(path)
    err: Optional[BaseException] = None
    for candidate in (path, retry_path):
        if candidate is None:
            continue
        candidate = Path(candidate)
        if not candidate.exists():
            continue
        try:
            meta = extract_metadata(candidate)
            if content_hash is not None:
                meta["content_hash"] = content_hash
            return meta
        except Exception as e:
            err = e
            logger.warning("Metadata extract failed for %s: %s", candidate, e)

    # Prefer a path that still exists for fallback mtime
    fallback_path = path
    if retry_path is not None and Path(retry_path).exists():
        fallback_path = Path(retry_path)
    elif not path.exists() and retry_path is not None:
        fallback_path = Path(retry_path)

    return fallback_metadata(
        fallback_path,
        error=str(err) if err else "metadata extract failed",
        content_hash=content_hash,
    )
