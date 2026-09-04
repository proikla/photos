from pathlib import Path

from photosort.hasher import sha256_file
from tests.conftest import make_jpeg


def test_same_bytes_same_hash(tmp_path: Path):
    a = make_jpeg(tmp_path / "a.jpg", color=(10, 20, 30))
    b = make_jpeg(tmp_path / "b.jpg", color=(10, 20, 30))
    # Re-save may differ; copy bytes instead
    c = tmp_path / "c.jpg"
    c.write_bytes(a.read_bytes())
    assert sha256_file(a) == sha256_file(c)
    assert sha256_file(a) != sha256_file(b) or a.read_bytes() == b.read_bytes()


def test_different_content_different_hash(tmp_path: Path):
    a = make_jpeg(tmp_path / "a.jpg", color=(255, 0, 0))
    b = make_jpeg(tmp_path / "b.jpg", color=(0, 255, 0))
    assert sha256_file(a) != sha256_file(b)
