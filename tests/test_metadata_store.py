import datetime as dt
from pathlib import Path

from photosort.metadata_store import resolve_metadata_records
from tests.conftest import make_jpeg


def test_resolve_scans_directory(tmp_path: Path):
    make_jpeg(
        tmp_path / "a.jpg",
        when=dt.datetime(2020, 1, 1),
        color=(1, 1, 1),
        lens="A",
        focal=(24, 1),
    )
    records, source = resolve_metadata_records(tmp_path)
    assert source.startswith("scan:")
    assert len(records) == 1
    assert records[0]["lens"] == "A"
