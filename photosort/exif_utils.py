"""EXIF date and camera metadata extraction via Pillow."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ExifTags

# Map tag names we care about
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

# Also check Exif IFD nested tags (Pillow 10+)
_EXIF_IFD = getattr(ExifTags, "Base", None)


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
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S.%f"):
        try:
            return dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _get_exif_dict(img: Image.Image) -> dict:
    """Flatten Pillow EXIF into a simple tag-id -> value map."""
    result: dict = {}
    try:
        exif = img.getexif()
    except Exception:
        return result
    if not exif:
        return result
    for k, v in exif.items():
        result[k] = v
    # Nested Exif IFD (0x8769)
    try:
        ifd = exif.get_ifd(0x8769)
        for k, v in ifd.items():
            result[k] = v
    except Exception:
        pass
    return result


def get_photo_datetime(path: Path) -> dt.datetime:
    """
    Date priority: EXIF DateTimeOriginal → DateTime → file mtime.
    Always returns a timezone-naive datetime.
    """
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
    mtime = path.stat().st_mtime
    return dt.datetime.fromtimestamp(mtime)


def extract_metadata(path: Path) -> dict[str, Any]:
    """Collect EXIF / file metadata into a plain dict."""
    meta: dict[str, Any] = {
        "path": str(path),
        "filename": path.name,
        "datetime": None,
        "camera": None,
        "lens": None,
        "aperture": None,
        "focal_length_mm": None,
        "shutter": None,
        "iso": None,
    }
    when = get_photo_datetime(path)
    meta["datetime"] = when.isoformat(sep=" ")

    try:
        with Image.open(path) as img:
            exif = _get_exif_dict(img)
    except Exception:
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
