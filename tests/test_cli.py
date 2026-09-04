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


def test_cli_stats_from_library_folder_without_json(tmp_path: Path, capsys):
    lib = tmp_path / "library"
    make_jpeg(
        lib / "2023" / "01" / "a.jpg",
        when=dt.datetime(2023, 1, 2, 10, 0, 0),
        color=(1, 2, 3),
        lens="Summilux 35",
        focal=(35, 1),
    )
    make_jpeg(
        lib / "2023" / "02" / "b.jpg",
        when=dt.datetime(2023, 2, 3, 11, 0, 0),
        color=(4, 5, 6),
        lens="Summilux 35",
        focal=(35, 1),
    )
    assert not (lib / "photosort_metadata.json").exists()
    rc = main(["stats", str(lib)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Summilux 35" in out
    assert "source: scan:" in out


def test_cli_stats_prefers_cached_json_unless_rescan(tmp_path: Path, capsys):
    lib = tmp_path / "library"
    make_jpeg(
        lib / "x.jpg",
        when=dt.datetime(2021, 1, 1),
        color=(9, 9, 9),
        lens="Live Lens",
        focal=(50, 1),
    )
    # Cached JSON with different lens name — should win without --rescan
    (lib / "photosort_metadata.json").write_text(
        '[{"lens": "Cached Lens", "focal_length_mm": 85}]\n',
        encoding="utf-8",
    )
    rc = main(["stats", str(lib)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Cached Lens" in out
    assert "Live Lens" not in out

    rc2 = main(["stats", str(lib), "--rescan"])
    assert rc2 == 0
    out2 = capsys.readouterr().out
    assert "Live Lens" in out2


def test_cli_organize_prints_progress(tmp_path: Path, capsys):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    make_jpeg(src / "p.jpg", when=dt.datetime(2022, 1, 1), color=(1, 2, 3))
    rc = main(["organize", str(src), str(dest)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "==>" in err
    assert "Found 1 image" in err or "Organizing" in err


def test_cli_quiet_hides_progress(tmp_path: Path, capsys):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    make_jpeg(src / "p.jpg", when=dt.datetime(2022, 1, 1), color=(3, 2, 1))
    rc = main(["organize", str(src), str(dest), "--quiet"])
    assert rc == 0
    err = capsys.readouterr().err
    assert "==>" not in err
