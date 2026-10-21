"""稳定性与真实库校验：同分选择确定、77 张图完整、旧接口兼容。"""
import json

import sticker_engine
from emotion_engine import analyze_context


def _run(text, n=5, relationship="unknown"):
    ctx = analyze_context(text)
    return [sticker_engine.select_sticker(ctx, relationship=relationship)["id"] for _ in range(n)]


def test_same_input_same_result():
    for text in ["今天好开心", "有点委屈", "抱抱我", "唉，好累"]:
        ids = _run(text)
        assert len(set(ids)) == 1, (text, ids)


def test_tie_break_is_stable_and_explainable():
    lib = {
        "stickers": [
            {"id": "z-2", "name": "同分B", "description": "", "emotion": ["开心"], "tags": [],
             "use_when": [], "avoid_when": [], "priority": 5, "file": "stickers/z2.png",
             "intensity_range": [4, 6]},
            {"id": "a-1", "name": "同分A", "description": "", "emotion": ["开心"], "tags": [],
             "use_when": [], "avoid_when": [], "priority": 5, "file": "stickers/a1.png",
             "intensity_range": [4, 6]},
        ]
    }
    sticker_engine.set_library(lib)
    ctx = {"emotion": ["开心"], "intensity": 5, "keywords": [], "actions": [], "intent": []}
    picked = {sticker_engine.select_sticker(ctx)["id"] for _ in range(10)}
    assert picked == {"a-1"}, picked


def test_higher_priority_wins_when_scores_tie():
    lib = {
        "stickers": [
            {"id": "p-5", "name": "低优先", "description": "", "emotion": ["开心"], "tags": [],
             "use_when": [], "avoid_when": [], "priority": 5, "file": "stickers/p5.png",
             "intensity_range": [4, 6]},
            {"id": "p-9", "name": "高优先", "description": "", "emotion": ["开心"], "tags": [],
             "use_when": [], "avoid_when": [], "priority": 9, "file": "stickers/p9.png",
             "intensity_range": [4, 6]},
        ]
    }
    sticker_engine.set_library(lib)
    ctx = {"emotion": ["开心"], "intensity": 5, "keywords": [], "actions": [], "intent": []}
    assert sticker_engine.select_sticker(ctx)["id"] == "p-9"


def test_real_library_is_intact(library):
    items = library["stickers"]
    assert len(items) == 77
    ids = [x["id"] for x in items]
    assert len(set(ids)) == 77
    files = [x["file"] for x in items]
    assert len(set(files)) == 77
    for item in items:
        lo, hi = item["intensity_range"]
        assert 1 <= lo <= hi <= 10, item["id"]
        assert item["file"].startswith("stickers/"), item["id"]
        assert item["id"] in item["file"], item["id"]


def test_legacy_items_still_match_after_stripping_new_fields(library):
    """去掉 mood_strength / trigger_actions 后，老图仍应能正常参与匹配。"""
    stripped = []
    for item in library["stickers"]:
        copy = dict(item)
        copy.pop("mood_strength", None)
        copy.pop("trigger_actions", None)
        stripped.append(copy)
    sticker_engine.set_library({"stickers": stripped})
    for text in ["今天好开心", "有点委屈", "好气啊", "抱抱我"]:
        assert sticker_engine.select_sticker(analyze_context(text)) is not None


def test_search_sticker_accepts_string_for_backward_compat(library):
    """老脚本 test.py / client_test.py 直接传字符串，不能再崩。"""
    result = sticker_engine.search_sticker("开心")
    assert result is not None and "id" in result


def test_select_sticker_returns_none_for_empty_context(library):
    assert sticker_engine.select_sticker("") is None
