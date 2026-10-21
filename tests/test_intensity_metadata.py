"""The maintained v2.2 index must have complete, valid strength annotations."""

import json
from pathlib import Path


def test_every_sticker_has_valid_intensity_range():
    data = json.loads((Path(__file__).parent / "fixtures" / "instructions_v22.json")
                      .read_text(encoding="utf-8"))
    assert data["stickers"]
    for item in data["stickers"]:
        bounds = item.get("intensity_range")
        assert isinstance(bounds, list) and len(bounds) == 2, item["id"]
        assert all(type(value) is int for value in bounds), item["id"]
        assert 1 <= bounds[0] <= bounds[1] <= 10, item["id"]
