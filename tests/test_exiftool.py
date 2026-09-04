import datetime as dt
from pathlib import Path

import pytest

from photosort.exif_utils import (
    _meta_from_exiftool_dict,
    exiftool_available,
    extract_metadata,
    extract_metadata_batch_exiftool,
)
from tests.conftest import make_jpeg


def test_meta_from_exiftool_dict_picks_lens_and_focal(tmp_path: Path):
    path = tmp_path / "a.CR2"
    path.write_bytes(b"not-a-real-raw")
    meta = _meta_from_exiftool_dict(
        path,
        {
            "DateTimeOriginal": "2022:05:06 07:08:09",
            "Make": "NIKON CORPORATION",
            "Model": "NIKON Z 6",
            "LensID": "157",
            "LensModel": "NIKKOR Z 50mm f/1.8 S",
            "FocalLength": 50,
            "FNumber": 1.8,
            "ExposureTime": 0.008,
            "ISO": 200,
        },
    )
    assert meta["lens"] == "NIKKOR Z 50mm f/1.8 S"
    assert meta["focal_length_mm"] == 50
    assert meta["aperture"] == "f/1.8"
    assert meta["camera"] == "NIKON CORPORATION NIKON Z 6"
    assert meta["meta_source"] == "exiftool"
    assert meta["datetime"].startswith("2022-05-06")


def test_lens_falls_back_to_lens_id(tmp_path: Path):
    path = tmp_path / "x.NEF"
    path.write_bytes(b"x")
    meta = _meta_from_exiftool_dict(
        path,
        {"LensID": "AF-S Nikkor 85mm f/1.8G", "FocalLength": 85},
    )
    assert meta["lens"] == "AF-S Nikkor 85mm f/1.8G"
    assert meta["focal_length_mm"] == 85


@pytest.mark.skipif(not exiftool_available(), reason="exiftool not installed")
def test_exiftool_reads_jpeg_lens(tmp_path: Path):
    path = make_jpeg(
        tmp_path / "t.jpg",
        when=dt.datetime(2021, 3, 4, 5, 6, 7),
        lens="Summicron 35",
        focal=(35, 1),
    )
    meta = extract_metadata(path)
    assert meta["lens"] == "Summicron 35"
    assert meta["focal_length_mm"] == 35
    assert meta["meta_source"] == "exiftool"

    batch = extract_metadata_batch_exiftool([path])
    assert str(path.resolve()) in batch
    assert batch[str(path.resolve())]["lens"] == "Summicron 35"
