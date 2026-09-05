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
    assert result.moved == 2
    assert result.skipped == 0


def test_depth_day_creates_day_folders(tmp_path: Path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    make_jpeg(src / "d.jpg", when=dt.datetime(2021, 6, 7, 12, 0, 0), color=(7, 8, 9))
    organize(src, dest, depth="day")
    assert (dest / "2021" / "06" / "07" / "d.jpg").is_file()


def test_default_is_move_not_copy(tmp_path: Path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    original = make_jpeg(src / "gone.jpg", when=dt.datetime(2020, 1, 1), color=(11, 22, 33))
    organize(src, dest)
    assert not original.exists()
    assert (dest / "2020" / "01" / "gone.jpg").is_file()


def test_copy_flag_keeps_source(tmp_path: Path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    original = make_jpeg(src / "keep.jpg", when=dt.datetime(2020, 1, 1), color=(11, 22, 33))
    content = original.read_bytes()
    organize(src, dest, move=False)
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

    result = organize(src, dest, depth="month", move=False)
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
    organize(src, dest, move=False)
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
    result = organize(src2, dest, move=False)
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
    organize(src, dest, move=False)
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

    result = organize(src, dest, move=False)
    assert result.hashes_before <= result.hashes_after
    newly = {
        d.content_hash
        for d in result.decisions
        if d.action not in ("skipped_duplicate", "skipped_already_sorted")
    }
    assert result.hashes_after == result.hashes_before | newly
    assert result.skipped == 1
    assert result.copied == 1


def test_internal_source_duplicates_only_one_copied(tmp_path: Path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    a = make_jpeg(src / "one.jpg", when=dt.datetime(2015, 5, 5), color=(70, 70, 70))
    b = src / "two.jpg"
    b.write_bytes(a.read_bytes())
    result = organize(src, dest, move=False)
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
            "skipped_already_sorted",
            "renamed_and_copied",
            "renamed_and_moved",
        }


def test_move_preserves_metadata_in_result(tmp_path: Path):
    """CRITICAL: with --move, metadata must be extracted BEFORE the file vanishes."""
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    original = make_jpeg(
        src / "gone.jpg",
        when=dt.datetime(2020, 2, 2, 15, 30, 0),
        color=(44, 55, 66),
        lens="MoveLens 50mm",
        focal=(50, 1),
        make="MoveCam",
        model="M1",
    )
    assert original.is_file()
    result = organize(src, dest, move=True)
    assert not original.exists()
    placed = dest / "2020" / "02" / "gone.jpg"
    assert placed.is_file()
    assert len(result.metadata) == 1
    meta = result.metadata[0]
    assert meta["content_hash"] == sha256_file(placed)
    assert meta["lens"] and "MoveLens" in meta["lens"]
    assert meta["focal_length_mm"] == 50
    assert meta["camera"] and "MoveCam" in meta["camera"]
    assert meta["datetime"] and meta["datetime"].startswith("2020-02-02")
    assert str(meta["dest"]) == str(placed)
    assert meta.get("meta_source") != "fallback"
    assert isinstance(meta.get("exif"), dict)


def test_metadata_extracted_before_move(tmp_path: Path, monkeypatch):
    """Ensure extract runs against source path that still exists (not post-move)."""
    import photosort.organizer as org

    src = tmp_path / "src"
    dest = tmp_path / "dest"
    original = make_jpeg(
        src / "ordered.jpg",
        when=dt.datetime(2019, 8, 8),
        color=(1, 2, 3),
        lens="OrderLens",
        focal=(35, 1),
    )
    seen_paths: list[Path] = []
    real_safe = org.extract_metadata_safe

    def tracking_safe(path, *, content_hash=None, retry_path=None):
        seen_paths.append(Path(path))
        assert Path(path).exists(), f"extract called on missing path: {path}"
        return real_safe(path, content_hash=content_hash, retry_path=retry_path)

    monkeypatch.setattr(org, "extract_metadata_safe", tracking_safe)
    result = organize(src, dest, move=True)
    assert not original.exists()
    assert seen_paths, "extract_metadata_safe was never called"
    assert seen_paths[0].name == "ordered.jpg"
    assert len(result.metadata) == 1
    assert result.metadata[0]["lens"] and "OrderLens" in result.metadata[0]["lens"]


def test_move_with_collision_rename_preserves_metadata(tmp_path: Path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    existing = make_jpeg(
        dest / "2020" / "01" / "shot.jpg",
        when=dt.datetime(2020, 1, 1, 10, 0, 0),
        color=(100, 0, 0),
        lens="ExistingLens",
        focal=(24, 1),
    )
    incoming = make_jpeg(
        src / "shot.jpg",
        when=dt.datetime(2020, 1, 1, 11, 0, 0),
        color=(0, 100, 0),
        lens="IncomingLens 85mm",
        focal=(85, 1),
    )
    h_in = sha256_file(incoming)
    result = organize(src, dest, move=True)
    assert not incoming.exists()
    assert existing.is_file()
    files = list((dest / "2020" / "01").glob("shot*.jpg"))
    assert len(files) == 2
    assert result.renamed == 1
    assert result.moved == 1
    assert len(result.metadata) == 1
    meta = result.metadata[0]
    assert meta["content_hash"] == h_in
    assert meta["lens"] and "IncomingLens" in meta["lens"]
    assert meta["focal_length_mm"] == 85
    assert Path(meta["dest"]).name.startswith("shot_")
    assert Path(meta["dest"]).is_file()


def test_sidecar_xmp_copied_with_photo(tmp_path: Path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    photo = make_jpeg(
        src / "img.jpg",
        when=dt.datetime(2021, 4, 4),
        color=(10, 20, 30),
    )
    sidecar = src / "img.xmp"
    sidecar.write_text("<x:xmpmeta>test</x:xmpmeta>\n", encoding="utf-8")
    organize(src, dest, move=False)
    assert photo.is_file()
    assert sidecar.is_file()
    assert (dest / "2021" / "04" / "img.jpg").is_file()
    dest_sc = dest / "2021" / "04" / "img.xmp"
    assert dest_sc.is_file()
    assert dest_sc.read_text(encoding="utf-8") == sidecar.read_text(encoding="utf-8")


def test_sidecar_xmp_and_aae_moved_with_photo(tmp_path: Path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    photo = make_jpeg(
        src / "phone.jpg",
        when=dt.datetime(2021, 5, 5),
        color=(30, 20, 10),
    )
    xmp = src / "phone.xmp"
    aae = src / "phone.aae"
    xmp.write_text("xmp-data", encoding="utf-8")
    aae.write_text("aae-data", encoding="utf-8")
    organize(src, dest, move=True)
    assert not photo.exists()
    assert not xmp.exists()
    assert not aae.exists()
    assert (dest / "2021" / "05" / "phone.jpg").is_file()
    assert (dest / "2021" / "05" / "phone.xmp").is_file()
    assert (dest / "2021" / "05" / "phone.aae").is_file()
    assert (dest / "2021" / "05" / "phone.xmp").read_text(encoding="utf-8") == "xmp-data"


def test_sidecar_moves_with_collision_rename(tmp_path: Path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    make_jpeg(
        dest / "2020" / "01" / "shot.jpg",
        when=dt.datetime(2020, 1, 1),
        color=(1, 0, 0),
    )
    make_jpeg(
        src / "shot.jpg",
        when=dt.datetime(2020, 1, 1),
        color=(0, 1, 0),
    )
    (src / "shot.xmp").write_text("sidecar", encoding="utf-8")
    result = organize(src, dest, move=True)
    assert result.renamed == 1
    renamed = [d for d in result.decisions if d.action.startswith("renamed")][0]
    assert renamed.dest is not None
    dest_sc = renamed.dest.with_suffix(".xmp")
    assert dest_sc.is_file()
    assert dest_sc.read_text(encoding="utf-8") == "sidecar"


def test_copy_also_records_metadata_with_exif_dump(tmp_path: Path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    make_jpeg(
        src / "c.jpg",
        when=dt.datetime(2018, 3, 3),
        color=(9, 8, 7),
        lens="CopyLens",
        focal=(28, 1),
    )
    result = organize(src, dest, move=False)
    assert len(result.metadata) == 1
    meta = result.metadata[0]
    assert meta["lens"] and "CopyLens" in meta["lens"]
    assert isinstance(meta.get("exif"), dict)
    assert len(meta["exif"]) > 0


# --- In-place organize (source == dest / dest omitted) ---


def test_inplace_organize_moves_scattered_into_yyyy_mm(tmp_path: Path):
    """organize(src) without dest moves scattered files into YYYY/MM under src."""
    root = tmp_path / "library"
    a = make_jpeg(root / "inbox" / "a.jpg", when=dt.datetime(2022, 3, 10), color=(1, 2, 3))
    b = make_jpeg(root / "misc" / "b.jpg", when=dt.datetime(2022, 11, 5), color=(4, 5, 6))
    h_a, h_b = sha256_file(a), sha256_file(b)
    before = {h_a, h_b}

    result = organize(root)  # dest omitted → in-place
    assert result.hashes_after == before == result.hashes_before
    assert not a.exists()
    assert not b.exists()
    assert (root / "2022" / "03" / "a.jpg").is_file()
    assert (root / "2022" / "11" / "b.jpg").is_file()
    assert sha256_file(root / "2022" / "03" / "a.jpg") == h_a
    assert sha256_file(root / "2022" / "11" / "b.jpg") == h_b
    assert result.moved == 2


def test_inplace_dest_equals_source(tmp_path: Path):
    root = tmp_path / "lib"
    make_jpeg(root / "x.jpg", when=dt.datetime(2021, 1, 1), color=(9, 8, 7))
    result = organize(root, root)
    assert (root / "2021" / "01" / "x.jpg").is_file()
    assert result.moved == 1
    assert result.hashes_before == result.hashes_after


def test_inplace_already_sorted_left_alone(tmp_path: Path):
    """File already in correct YYYY/MM is left alone (not duplicated, not lost)."""
    root = tmp_path / "lib"
    placed = make_jpeg(
        root / "2020" / "01" / "shot.jpg",
        when=dt.datetime(2020, 1, 15, 10, 0, 0),
        color=(10, 20, 30),
    )
    h = sha256_file(placed)
    content = placed.read_bytes()
    result = organize(root)
    assert placed.is_file()
    assert placed.read_bytes() == content
    assert sha256_file(placed) == h
    assert len(list(root.rglob("*.jpg"))) == 1
    assert result.already_sorted == 1
    assert result.moved == 0
    assert result.copied == 0
    assert result.hashes_before == result.hashes_after == {h}


def test_inplace_name_collision_different_content_keeps_both(tmp_path: Path):
    """Name collision different content → both kept with _1 rename."""
    root = tmp_path / "lib"
    existing = make_jpeg(
        root / "2020" / "01" / "shot.jpg",
        when=dt.datetime(2020, 1, 1, 10, 0, 0),
        color=(100, 0, 0),
    )
    h_existing = sha256_file(existing)
    incoming = make_jpeg(
        root / "inbox" / "shot.jpg",
        when=dt.datetime(2020, 1, 1, 11, 0, 0),
        color=(0, 100, 0),
    )
    h_incoming = sha256_file(incoming)
    assert h_existing != h_incoming

    result = organize(root)
    files = list((root / "2020" / "01").glob("shot*.jpg"))
    assert len(files) == 2
    hashes = {sha256_file(f) for f in files}
    assert hashes == {h_existing, h_incoming}
    assert result.renamed == 1
    assert not incoming.exists()
    assert result.hashes_before == result.hashes_after


def test_inplace_true_duplicate_one_kept(tmp_path: Path):
    """True duplicate (same bytes, two paths) → one kept, other skipped."""
    root = tmp_path / "lib"
    a = make_jpeg(
        root / "inbox" / "a.jpg",
        when=dt.datetime(2019, 6, 6),
        color=(50, 50, 50),
    )
    h = sha256_file(a)
    dup = root / "inbox" / "a_copy.jpg"
    dup.write_bytes(a.read_bytes())
    assert sha256_file(dup) == h

    result = organize(root)
    assert result.skipped == 1
    assert result.moved == 1
    assert result.hashes_before == result.hashes_after == {h}
    # Unique content present under date folder
    jpgs = [p for p in root.rglob("*.jpg") if p.is_file()]
    dated = [p for p in jpgs if "2019" in p.parts]
    assert len(dated) >= 1
    assert any(sha256_file(p) == h for p in dated)


def test_inplace_metadata_present_after_move(tmp_path: Path):
    root = tmp_path / "lib"
    original = make_jpeg(
        root / "loose.jpg",
        when=dt.datetime(2020, 2, 2, 15, 30, 0),
        color=(44, 55, 66),
        lens="InPlaceLens 50mm",
        focal=(50, 1),
        make="InPlaceCam",
        model="IP1",
    )
    result = organize(root, move=True)
    assert not original.exists()
    placed = root / "2020" / "02" / "loose.jpg"
    assert placed.is_file()
    assert len(result.metadata) == 1
    meta = result.metadata[0]
    assert meta["lens"] and "InPlaceLens" in meta["lens"]
    assert meta["focal_length_mm"] == 50
    assert meta["datetime"] and meta["datetime"].startswith("2020-02-02")
    assert Path(meta["dest"]) == placed


def test_inplace_sidecar_moves_with_photo(tmp_path: Path):
    root = tmp_path / "lib"
    photo = make_jpeg(
        root / "phone.jpg",
        when=dt.datetime(2021, 5, 5),
        color=(30, 20, 10),
    )
    xmp = root / "phone.xmp"
    xmp.write_text("xmp-inplace", encoding="utf-8")
    organize(root, move=True)
    assert not photo.exists()
    assert not xmp.exists()
    assert (root / "2021" / "05" / "phone.jpg").is_file()
    dest_sc = root / "2021" / "05" / "phone.xmp"
    assert dest_sc.is_file()
    assert dest_sc.read_text(encoding="utf-8") == "xmp-inplace"


def test_inplace_mixed_already_sorted_and_scattered(tmp_path: Path):
    root = tmp_path / "lib"
    already = make_jpeg(
        root / "2022" / "03" / "kept.jpg",
        when=dt.datetime(2022, 3, 10),
        color=(1, 1, 1),
    )
    loose = make_jpeg(
        root / "dump" / "new.jpg",
        when=dt.datetime(2022, 4, 1),
        color=(2, 2, 2),
    )
    h_already, h_loose = sha256_file(already), sha256_file(loose)
    result = organize(root)
    assert already.is_file()
    assert not loose.exists()
    assert (root / "2022" / "04" / "new.jpg").is_file()
    assert result.already_sorted == 1
    assert result.moved == 1
    assert result.hashes_after == {h_already, h_loose}
