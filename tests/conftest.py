"""Shared fixtures: synthetic JPEGs with optional EXIF via piexif/Pillow."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import piexif
import pytest
from PIL import Image


def _exif_bytes(
    when: dt.datetime | None = None,
    *,
    make: str = "TestCam",
    model: str = "Model X",
    lens: str = "TestLens 35mm f/1.8",
    fnumber: tuple[int, int] = (18, 10),
    focal: tuple[int, int] = (35, 1),
    exposure: tuple[int, int] = (1, 125),
    iso: int = 200,
) -> bytes:
    zeroth = {
        piexif.ImageIFD.Make: make.encode("utf-8"),
        piexif.ImageIFD.Model: model.encode("utf-8"),
        piexif.ImageIFD.Software: b"photosort-test",
    }
    exif = {
        piexif.ExifIFD.FNumber: fnumber,
        piexif.ExifIFD.FocalLength: focal,
        piexif.ExifIFD.ExposureTime: exposure,
        piexif.ExifIFD.ISOSpeedRatings: iso,
        piexif.ExifIFD.LensModel: lens.encode("utf-8"),
    }
    if when is not None:
        stamp = when.strftime("%Y:%m:%d %H:%M:%S")
        zeroth[piexif.ImageIFD.DateTime] = stamp.encode("utf-8")
        exif[piexif.ExifIFD.DateTimeOriginal] = stamp.encode("utf-8")
        exif[piexif.ExifIFD.DateTimeDigitized] = stamp.encode("utf-8")
    return piexif.dump({"0th": zeroth, "Exif": exif, "1st": {}, "GPS": {}})


def make_jpeg(
    path: Path,
    *,
    color: tuple[int, int, int] = (200, 50, 50),
    size: tuple[int, int] = (64, 48),
    when: dt.datetime | None = None,
    with_exif: bool = True,
    **exif_kw,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, color)
    save_kw = {"format": "JPEG", "quality": 90}
    if with_exif:
        save_kw["exif"] = _exif_bytes(when, **exif_kw)
    img.save(path, **save_kw)
    if when is not None and not with_exif:
        # Set mtime for fallback testing
        ts = when.timestamp()
        import os

        os.utime(path, (ts, ts))
    return path


@pytest.fixture
def jpeg_factory(tmp_path: Path):
    def _factory(name: str, **kwargs) -> Path:
        return make_jpeg(tmp_path / name, **kwargs)

    return _factory
