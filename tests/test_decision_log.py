"""Tests for human-readable action log formatting."""

from __future__ import annotations

from pathlib import Path

from photosort.decision_log import (
    ActionLogger,
    format_action_entry,
    short_hash,
)


def test_short_hash_takes_first_12_hex():
    full = "a1b2c3d4e5f6789012345678abcdef01" + "deadbeef"
    assert short_hash(full) == "a1b2c3d4e5f6"
    assert short_hash("sha256=" + full) == "a1b2c3d4e5f6"
    assert short_hash("SHA256=AABBCCDDEEFF001122334455") == "aabbccddeeff"
    assert short_hash("") == ""
    assert short_hash(None) == ""


def test_format_move_structure():
    block = format_action_entry(
        label="MOVE",
        title="DSC00197.ARW",
        why="sort into date folder (EXIF)",
        proof="sha256=a1b2c3d4e5f6",
        from_path="/Pictures/misc/DSC00197.ARW",
        to_path="/Pictures/2022/03/DSC00197.ARW",
    )
    lines = block.splitlines()
    assert lines[0] == "MOVE  DSC00197.ARW"
    assert lines[1].startswith("  from   ")
    assert "/Pictures/misc/DSC00197.ARW" in lines[1]
    assert lines[2].startswith("  to     ")
    assert "/Pictures/2022/03/DSC00197.ARW" in lines[2]
    assert lines[3] == "  why    sort into date folder (EXIF)"
    assert lines[4] == "  proof  sha256=a1b2c3d4e5f6"
    # Readable structure: label line, then indented from/to/why/proof
    assert all(lines[i].startswith("  ") for i in range(1, 5))
    assert "MOVE" in block and "why" in block and "proof" in block


def test_format_rename_structure():
    block = format_action_entry(
        label="RENAME",
        title="shot.jpg → shot_1.jpg",
        why="name taken by different content",
        proof="new=sha256=111122223333  existing=sha256=222233334444 at 2020/01/shot.jpg",
        from_path="/inbox/shot.jpg",
        to_path="/2020/01/shot_1.jpg",
    )
    lines = block.splitlines()
    assert lines[0] == "RENAME  shot.jpg → shot_1.jpg"
    assert "→" in lines[0]
    assert lines[1].startswith("  from   ")
    assert lines[2].startswith("  to     ")
    assert lines[3] == "  why    name taken by different content"
    assert lines[4].startswith("  proof  ")
    assert "new=sha256=" in lines[4]
    assert "existing=sha256=" in lines[4]
    assert "shot.jpg" in lines[4]


def test_format_skip_structure():
    block = format_action_entry(
        label="SKIP",
        title="copy.jpg",
        why="exact duplicate",
        proof="sha256=aaaa1111bbbb already at 2020/01/orig.jpg",
    )
    lines = block.splitlines()
    assert lines[0] == "SKIP  copy.jpg"
    # SKIP has no from/to — only why + proof
    assert lines[1] == "  why    exact duplicate"
    assert lines[2].startswith("  proof  ")
    assert "already at" in lines[2]
    assert "from" not in block
    assert "to" not in block


def test_format_keep_structure():
    block = format_action_entry(
        label="KEEP",
        title="2020/01/a.jpg",
        why="already in correct date folder",
        proof="sha256=bbbb2222cccc",
    )
    lines = block.splitlines()
    assert lines[0] == "KEEP  2020/01/a.jpg"
    assert lines[1] == "  why    already in correct date folder"
    assert lines[2] == "  proof  sha256=bbbb2222cccc"


def test_action_logger_writes_file_and_header(tmp_path: Path, caplog):
    import logging

    log_path = tmp_path / "photosort_actions.log"
    al = ActionLogger(log_path, logger=logging.getLogger("photosort.test_actions"))
    with caplog.at_level(logging.INFO, logger="photosort.test_actions"):
        al.write_header(
            mode="MOVE",
            source="/src",
            dest="/dest",
            depth="month",
            dry_run=False,
        )
        al.log_entry(
            label="MOVE",
            title="a.jpg",
            why="sort into date folder (EXIF)",
            proof="sha256=abcdef012345",
            from_path="/src/a.jpg",
            to_path="/dest/2020/01/a.jpg",
        )
        al.write_footer(summary="done  copied/moved=1")
    al.close()

    text = log_path.read_text(encoding="utf-8")
    assert "photosort actions" in text
    assert "mode    MOVE" in text
    assert "source  /src" in text
    assert "dest    /dest" in text
    assert "MOVE  a.jpg" in text
    assert "  why    sort into date folder (EXIF)" in text
    assert "done  copied/moved=1" in text
    # logger.info got the block too
    assert any("MOVE  a.jpg" in r.getMessage() for r in caplog.records)


def test_organize_emits_pretty_actions(tmp_path: Path):
    """organize() writes MOVE / RENAME / SKIP / KEEP blocks via ActionLogger."""
    import datetime as dt

    from photosort.hasher import sha256_file
    from photosort.organizer import organize
    from tests.conftest import make_jpeg

    src = tmp_path / "src"
    dest = tmp_path / "dest"
    # Pre-seed dest: one file that will conflict by name, one duplicate target
    existing = make_jpeg(
        dest / "2020" / "01" / "shot.jpg",
        when=dt.datetime(2020, 1, 1, 10, 0, 0),
        color=(100, 0, 0),
    )
    h_existing = sha256_file(existing)
    make_jpeg(
        dest / "2018" / "04" / "orig.jpg",
        when=dt.datetime(2018, 4, 4),
        color=(9, 9, 9),
    )
    placed_keep = make_jpeg(
        dest / "2019" / "05" / "keepme.jpg",
        when=dt.datetime(2019, 5, 5),
        color=(3, 3, 3),
    )

    make_jpeg(
        src / "fresh.jpg",
        when=dt.datetime(2021, 7, 7),
        color=(1, 2, 3),
    )
    make_jpeg(
        src / "shot.jpg",
        when=dt.datetime(2020, 1, 1, 11, 0, 0),
        color=(0, 100, 0),
    )
    # Exact duplicate of orig.jpg
    dup = src / "copy.jpg"
    dup.write_bytes((dest / "2018" / "04" / "orig.jpg").read_bytes())

    actions = tmp_path / "actions.log"
    al = ActionLogger(actions)
    al.write_header(mode="COPY", source=src, dest=dest, depth="month")
    # In-place KEEP: organize dest onto itself for keepme — instead run organize
    # from src, then a second organize on dest for KEEP.
    result = organize(src, dest, move=False, action_logger=al)
    al.close()

    text = actions.read_text(encoding="utf-8")
    assert "COPY  fresh.jpg" in text
    assert "  why    sort into date folder (EXIF)" in text
    assert "RENAME  shot.jpg → shot_1.jpg" in text
    assert "name taken by different content" in text
    assert "SKIP  copy.jpg" in text
    assert "exact duplicate" in text
    assert "sha256=" in text
    # short hashes only (12 hex) appear after sha256= in proof lines — not full 64
    import re

    for m in re.finditer(r"sha256=([0-9a-f]+)", text):
        assert len(m.group(1)) == 12, m.group(1)

    assert result.copied + result.renamed >= 2
    assert result.skipped == 1
    assert h_existing == sha256_file(existing)

    # KEEP path: organize dest in-place
    actions2 = tmp_path / "actions_keep.log"
    al2 = ActionLogger(actions2)
    organize(dest, dest, move=True, action_logger=al2)
    al2.close()
    keep_text = actions2.read_text(encoding="utf-8")
    assert "KEEP" in keep_text
    assert "already in correct date folder" in keep_text
    assert placed_keep.is_file()
