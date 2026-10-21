"""动作意图召回：trigger_actions 优先，action 降级兜底，旧图不被当成万能匹配。"""
from emotion_engine import analyze_context
from sticker_engine import score_item, select_sticker


def _select(text, relationship="unknown"):
    return select_sticker(analyze_context(text), relationship=relationship)


def test_hug_action_recall():
    item = _select("抱抱我")
    assert item is not None
    assert item["id"] in {"cat-005", "cat-025"}, item["id"]


def test_kiss_action_recall():
    item = _select("亲亲")
    assert item is not None
    assert item["id"] in {"cat-025", "cat-042"}, item["id"]


def test_proposal_action_recall():
    item = _select("我要单膝跪地求婚，把戒指给你")
    assert item is not None
    assert item["id"] == "cat-006", item["id"]


def test_heart_gesture_action_recall():
    item = _select("给你比心")
    assert item is not None
    assert item["id"] in {"cat-010", "cat-016"}, item["id"]


def test_flower_action_recall():
    item = _select("送花给你")
    assert item is not None
    assert item["id"] in {"cat-037", "cat-023", "cat-066"}, item["id"]


def test_trigger_action_beats_plain_tag(by_id):
    ctx = analyze_context("抱抱")
    with_trigger = score_item(by_id["cat-005"], ctx)   # trigger_actions 含 拥抱
    without = score_item(by_id["cat-060"], ctx)        # 无 trigger_actions、无相关标签
    assert with_trigger["breakdown"].get("trigger_action", 0) > 0
    assert with_trigger["score"] > without["score"]


def test_action_fallback_uses_action_field_only():
    """没有 trigger_actions 时，只允许用 action 字段做降级，不能靠 emotion 冒充动作。"""
    ctx = analyze_context("抱抱")
    legacy = {"id": "legacy-act", "name": "旧图", "description": "", "emotion": ["喜欢"],
              "tags": [], "use_when": [], "avoid_when": [], "priority": 5,
              "file": "stickers/x.png", "intensity_range": [4, 8], "action": ["拥抱"]}
    scored = score_item(legacy, ctx)
    assert scored["breakdown"].get("action_fallback", 0) > 0
    assert "trigger_action" not in scored["breakdown"]


def test_plain_emotion_word_does_not_act_as_action():
    """普通情绪词不应被当成动作意图。"""
    ctx = analyze_context("我今天很开心")
    assert ctx["actions"] == []
