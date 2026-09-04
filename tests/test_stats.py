from photosort.stats import coverage, format_stats, most_used_focal_lengths, most_used_lenses


def test_most_used_lenses_and_focals():
    records = [
        {"lens": "35mm f/1.8", "focal_length_mm": 35},
        {"lens": "35mm f/1.8", "focal_length_mm": 35},
        {"lens": "85mm f/1.8", "focal_length_mm": 85},
        {"lens": None, "focal_length_mm": 50},
        {"lens": "35mm f/1.8", "focal_length_mm": 28},
    ]
    assert most_used_lenses(records)[0] == ("35mm f/1.8", 3)
    focals = most_used_focal_lengths(records, lens="35mm f/1.8")
    assert focals[0] == (35, 2)
    text = format_stats(records)
    assert "Photos scanned: 5" in text
    assert "35mm f/1.8" in text
    assert "85mm" in text
    assert "no lens EXIF" in text
    cov = coverage(records)
    assert cov["total"] == 5
    assert cov["with_lens"] == 4
    assert cov["without_lens"] == 1


def test_focal_length_histogram_sorted_min_to_max():
    from photosort.stats import focal_length_histogram

    records = [
        {"focal_length_mm": 85},
        {"focal_length_mm": 24},
        {"focal_length_mm": 24},
        {"focal_length_mm": 50},
        {"lens": "x", "focal_length_mm": None},
    ]
    hist = focal_length_histogram(records)
    assert hist == [(24.0, 2), (50.0, 1), (85.0, 1)]


def test_plot_focal_lengths_writes_png(tmp_path):
    from photosort.stats import matplotlib_available, plot_focal_lengths

    if not matplotlib_available():
        import pytest
        pytest.skip("matplotlib not installed")
    records = [
        {"focal_length_mm": 35},
        {"focal_length_mm": 35},
        {"focal_length_mm": 85},
    ]
    out = tmp_path / "focals.png"
    assert plot_focal_lengths(records, out) is True
    assert out.is_file() and out.stat().st_size > 0
