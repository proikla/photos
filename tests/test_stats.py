from photosort.stats import format_stats, most_used_focal_lengths, most_used_lenses


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
    assert "35mm f/1.8" in text
    assert "85mm" in text
