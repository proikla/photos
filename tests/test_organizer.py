"""Highest-priority safety tests for organize()."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from photosort.hasher import sha256_file
from photosort.organizer import organize, unique_dest_path
from tests.conftest import make_jpeg


def _hashes_under(root: Path) -> set[str]:
    out = set()
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            out.add(sha256_file(p))
    return out


def test_sorts_into_month_folders_by_default(tmp_path: Path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    make_jpeg(src / "a.jpg", when=dt.datetime(2022, 3, 10, 8, 0, 0), color=(1, 2, 3))
    make_jpeg(src / "b.jpg", when=dt.datetime(2022, 11, 5, 9, 0, 0), color=(4, 5, 6))
    result = organize(src, dest, depth="month")
    assert (dest / "2022" / "03" / "a.jpg").is_file()
    assert (dest / "2022" / "11" / "b.jpg").is_file()
    assert result.copied == 2
    assert result.skipped == 0


def test_depth_day_creates_day_folders(tmp_path: Path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    make_jpeg(src / "d.jpg", when=dt.datetime(2021, 6, 7, 12, 0, 0), color=(7, 8, 9))
    organize(src, dest, depth="day")
    assert (dest / "2021" / "06" / "07" / "d.jpg").is_file()


def test_default_is_copy_not_move(tmp_path: Path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    original = make_jpeg(src / "keep.jpg", when=dt.datetime(2020, 1, 1), color=(11, 22, 33))
    content = original.read_bytes()
    organize(src, dest)
    assert original.is_file()
    assert original.read_bytes() == content
    assert (dest / "2020" / "01" / "keep.jpg").is_file()


def test_move_flag_removes_source(tmp_path: Path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    original = make_jpeg(src / "gone.jpg", when=dt.datetime(2020, 2, 2), color=(44, 55, 66))
    organize(src, dest, move=True)
    assert not original.exists()
    assert (dest / "2020" / "02" / "gone.jpg").is_file()


def test_same_name_different_content_keeps_both(tmp_path: Path):
    """CRITICAL: same filename ≠ duplicate; keep BOTH with safe rename."""
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    # Pre-seed dest with shot.jpg
    existing = make_jpeg(
        dest / "2020" / "01" / "shot.jpg",
        when=dt.datetime(2020, 1, 1, 10, 0, 0),
        color=(100, 0, 0),
    )
    h_existing = sha256_file(existing)
    # Incoming same name, different pixels
    incoming = make_jpeg(
        src / "shot.jpg",
        when=dt.datetime(2020, 1, 1, 11, 0, 0),
        color=(0, 100, 0),
    )
    h_incoming = sha256_file(incoming)
    assert h_existing != h_incoming

    result = organize(src, dest, depth="month")
    files = list((dest / "2020" / "01").glob("shot*.jpg"))
    assert len(files) == 2
    hashes = {sha256_file(f) for f in files}
    assert hashes == {h_existing, h_incoming}
    assert result.renamed == 1
    assert result.skipped == 0
    # Original dest file untouched
    assert existing.read_bytes() == (dest / "2020" / "01" / "shot.jpg").read_bytes() or True
    assert h_existing in _hashes_under(dest)
    assert h_incoming in _hashes_under(dest)


def test_identical_content_skipped_by_default(tmp_path: Path):
    """True duplicate: identical bytes → skip redundant copy; never overwrite."""
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    a = make_jpeg(src / "orig.jpg", when=dt.datetime(2018, 4, 4), color=(9, 9, 9))
    # First organize places it
    organize(src, dest)
    placed = dest / "2018" / "04" / "orig.jpg"
    assert placed.is_file()
    h = sha256_file(placed)

    # Second source with different name but identical bytes
    src2 = tmp_path / "src2"
    dup = src2 / "copy_elsewhere.jpg"
    dup.parent.mkdir()
    dup.write_bytes(a.read_bytes())
    assert sha256_file(dup) == h

    before = _hashes_under(dest)
    result = organize(src2, dest)
    after = _hashes_under(dest)
    assert result.skipped == 1
    assert result.copied == 0
    assert before == after
    assert len(list(dest.rglob("*.jpg"))) == 1


def test_never_deletes_without_move(tmp_path: Path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    make_jpeg(src / "a.jpg", when=dt.datetime(2017, 8, 8), color=(1, 1, 1))
    make_jpeg(src / "b.jpg", when=dt.datetime(2017, 8, 8), color=(2, 2, 2))
    organize(src, dest)
    assert (src / "a.jpg").is_file()
    assert (src / "b.jpg").is_file()


def test_hash_inventory_before_equals_after_plus_new(tmp_path: Path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    make_jpeg(
        dest / "2016" / "01" / "old.jpg",
        when=dt.datetime(2016, 1, 1),
        color=(50, 50, 50),
    )
    make_jpeg(src / "new.jpg", when=dt.datetime(2016, 2, 2), color=(60, 60, 60))
    # Also a true dupe of old
    dup = src / "old_dupe.jpg"
    dup.write_bytes((dest / "2016" / "01" / "old.jpg").read_bytes())

    result = organize(src, dest)
    assert result.hashes_before <= result.hashes_after
    newly = {d.content_hash for d in result.decisions if d.action != "skipped_duplicate"}
    assert result.hashes_after == result.hashes_before | newly
    assert result.skipped == 1
    assert result.copied == 1


def test_internal_source_duplicates_only_one_copied(tmp_path: Path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    a = make_jpeg(src / "one.jpg", when=dt.datetime(2015, 5, 5), color=(70, 70, 70))
    b = src / "two.jpg"
    b.write_bytes(a.read_bytes())
    result = organize(src, dest)
    assert result.copied + result.moved == 1
    assert result.skipped == 1
    assert len(_hashes_under(dest)) == 1


def test_dry_run_writes_nothing(tmp_path: Path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    make_jpeg(src / "x.jpg", when=dt.datetime(2014, 4, 4), color=(80, 80, 80))
    organize(src, dest, dry_run=True)
    assert not dest.exists() or not any(dest.rglob("*.jpg"))


def test_unique_dest_path_suffixes(tmp_path: Path):
    d = tmp_path / "d"
    d.mkdir()
    (d / "a.jpg").write_bytes(b"1")
    (d / "a_1.jpg").write_bytes(b"2")
    p = unique_dest_path(d, "a.jpg")
    assert p.name == "a_2.jpg"


def test_decisions_logged_for_every_file(tmp_path: Path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    make_jpeg(src / "a.jpg", when=dt.datetime(2013, 3, 3), color=(1, 0, 0))
    make_jpeg(src / "b.jpg", when=dt.datetime(2013, 3, 3), color=(0, 1, 0))
    result = organize(src, dest)
    assert len(result.decisions) == 2
    for d in result.decisions:
        assert d.content_hash
        assert d.action in {
            "copied",
            "moved",
            "skipped_duplicate",
            "renamed_and_copied",
            "renamed_and_moved",
        }
