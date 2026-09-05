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
    captured = capsys.readouterr()
    assert "Summilux 35" in captured.out
    assert "source: scan:" in captured.out


def test_cli_stats_walks_tree_by_default_even_if_cache_exists(tmp_path: Path, capsys):
    lib = tmp_path / "library"
    make_jpeg(
        lib / "x.jpg",
        when=dt.datetime(2021, 1, 1),
        color=(9, 9, 9),
        lens="Live Lens",
        focal=(50, 1),
    )
    (lib / "photosort_metadata.json").write_text(
        '[{"lens": "Cached Lens", "focal_length_mm": 85}]\n',
        encoding="utf-8",
    )
    rc = main(["stats", str(lib)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Live Lens" in captured.out
    assert "source: scan:" in captured.out

    rc2 = main(["stats", str(lib), "--cache"])
    assert rc2 == 0
    captured2 = capsys.readouterr()
    assert "Cached Lens" in captured2.out


def test_cli_stats_walks_nested_directories(tmp_path: Path, capsys):
    lib = tmp_path / "library"
    make_jpeg(
        lib / "2020" / "01" / "deep" / "a.jpg",
        when=dt.datetime(2020, 1, 1),
        color=(1, 0, 0),
        lens="Nested A",
        focal=(24, 1),
    )
    make_jpeg(
        lib / "misc" / "b.jpg",
        when=dt.datetime(2020, 2, 2),
        color=(0, 1, 0),
        lens="Nested B",
        focal=(35, 1),
    )
    rc = main(["stats", str(lib)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Nested A" in captured.out
    assert "Nested B" in captured.out
    assert "Found 2 image" in captured.err


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


def test_progress_bar_contains_blocks():
    from io import StringIO
    from photosort.progress import Progress

    buf = StringIO()
    p = Progress(stream=buf, bar_width=10)
    p.item(5, 10, "photo.jpg")
    p.done()
    text = buf.getvalue()
    assert "█" in text
    assert "░" in text
    assert "50%" in text


def test_cli_organize_move_writes_metadata_json(tmp_path: Path):
    """Regression: move must still populate photosort_metadata.json with EXIF."""
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    original = make_jpeg(
        src / "m.jpg",
        when=dt.datetime(2022, 6, 6, 10, 0, 0),
        color=(12, 34, 56),
        lens="CLI Move Lens",
        focal=(40, 1),
    )
    rc = main(["organize", str(src), str(dest), "--move", "--quiet"])
    assert rc == 0
    assert not original.exists()
    assert (dest / "2022" / "06" / "m.jpg").is_file()
    meta_path = dest / "photosort_metadata.json"
    assert meta_path.is_file()
    import json
    records = json.loads(meta_path.read_text(encoding="utf-8"))
    assert len(records) == 1
    assert records[0]["lens"] and "CLI Move Lens" in records[0]["lens"]
    assert records[0]["focal_length_mm"] == 40
    assert records[0].get("meta_source") != "fallback"
    assert isinstance(records[0].get("exif"), dict)


def test_cli_default_is_move_without_copy(tmp_path: Path):
    """Default CLI is move: without --copy, source file leaves inbox."""
    src = tmp_path / "inbox"
    dest = tmp_path / "library"
    original = make_jpeg(src / "p.jpg", when=dt.datetime(2022, 1, 1), color=(1, 2, 3))
    rc = main(["organize", str(src), str(dest), "--quiet"])
    assert rc == 0
    assert not original.exists()
    assert (dest / "2022" / "01" / "p.jpg").is_file()


def test_cli_copy_keeps_source(tmp_path: Path):
    src = tmp_path / "inbox"
    dest = tmp_path / "library"
    original = make_jpeg(src / "p.jpg", when=dt.datetime(2022, 1, 1), color=(3, 2, 1))
    content = original.read_bytes()
    rc = main(["organize", str(src), str(dest), "--copy", "--quiet"])
    assert rc == 0
    assert original.is_file()
    assert original.read_bytes() == content
    assert (dest / "2022" / "01" / "p.jpg").is_file()


def test_cli_inplace_omitted_dest(tmp_path: Path, capsys):
    root = tmp_path / "photos"
    make_jpeg(root / "loose.jpg", when=dt.datetime(2021, 7, 7), color=(7, 7, 7))
    rc = main(["organize", str(root)])
    assert rc == 0
    assert (root / "2021" / "07" / "loose.jpg").is_file()
    assert not (root / "loose.jpg").exists()
    err = capsys.readouterr().err
    assert "in-place sort under" in err
    assert "(move)" in err


def test_cli_inplace_inventory_ok_with_already_sorted(tmp_path: Path, capsys):
    root = tmp_path / "lib"
    make_jpeg(
        root / "2020" / "01" / "a.jpg",
        when=dt.datetime(2020, 1, 1),
        color=(1, 0, 0),
    )
    make_jpeg(
        root / "dump" / "b.jpg",
        when=dt.datetime(2020, 2, 2),
        color=(0, 1, 0),
    )
    rc = main(["organize", str(root), "--quiet"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "inventory: OK" in out
    assert "already sorted:" in out
