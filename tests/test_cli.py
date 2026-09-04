import datetime as dt
from pathlib import Path

from photosort.cli import main
from tests.conftest import make_jpeg


def test_cli_organize_and_stats(tmp_path: Path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    make_jpeg(
        src / "p.jpg",
        when=dt.datetime(2022, 9, 9, 10, 0, 0),
        color=(12, 34, 56),
        lens="CLI Lens 40mm",
        focal=(40, 1),
    )
    rc = main(["organize", str(src), str(dest), "--depth", "month"])
    assert rc == 0
    assert (dest / "2022" / "09" / "p.jpg").is_file()
    meta = dest / "photosort_metadata.json"
    assert meta.is_file()
    rc2 = main(["stats", str(meta)])
    assert rc2 == 0
