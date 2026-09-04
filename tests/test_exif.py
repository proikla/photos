import datetime as dt
import os
from pathlib import Path

from photosort.exif_utils import extract_metadata, get_photo_datetime
from tests.conftest import make_jpeg


def test_datetime_from_exif_original(tmp_path: Path):
    when = dt.datetime(2023, 7, 15, 14, 30, 0)
    p = make_jpeg(tmp_path / "x.jpg", when=when, with_exif=True)
    got = get_photo_datetime(p)
    assert got == when


def test_datetime_falls_back_to_mtime(tmp_path: Path):
    when = dt.datetime(2019, 1, 2, 3, 4, 5)
    p = make_jpeg(tmp_path / "y.jpg", with_exif=False)
    ts = when.timestamp()
    os.utime(p, (ts, ts))
    got = get_photo_datetime(p)
    assert got.year == 2019
    assert got.month == 1
    assert got.day == 2


def test_extract_metadata_fields(tmp_path: Path):
    when = dt.datetime(2024, 5, 1, 12, 0, 0)
    p = make_jpeg(
        tmp_path / "z.jpg",
        when=when,
        make="Nikon",
        model="Z6",
        lens="NIKKOR Z 50mm f/1.8 S",
        fnumber=(18, 10),
        focal=(50, 1),
        exposure=(1, 250),
        iso=400,
    )
    meta = extract_metadata(p)
    assert meta["camera"] and "Nikon" in meta["camera"]
    assert meta["lens"] and "50mm" in meta["lens"]
    assert meta["aperture"] == "f/1.8"
    assert meta["focal_length_mm"] == 50
    assert meta["shutter"] == "1/250"
    assert meta["iso"] == 400
    assert meta["datetime"].startswith("2024-05-01")
