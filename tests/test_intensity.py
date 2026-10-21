"""强度匹配：区间内 / 区间外 / 缺字段，以及 mood_strength 不参与打分。"""
from emotion_engine import analyze_context
from sticker_engine import score_item, select_sticker


def _pick(text, relationship="unknown"):
    ctx = analyze_context(text)
    item = select_sticker(ctx, relationship=relationship)
    assert item is not None, (text, ctx)
    lo, hi = item["intensity_range"]
    # 引擎把「距区间 1 分」视为可接受的近似匹配（W_INTENSITY_EDGE），
    # 因此这里放宽到 ±1；再远就说明强度匹配失效了。
    assert lo - 1 <= ctx["intensity"] <= hi + 1, (
        "选中图片的强度区间 %s 与对话强度 %s 相差超过 1（%s -> %s）"
        % ([lo, hi], ctx["intensity"], text, item["id"])
    )
    return item, ctx


def test_light_anger():
    item, ctx = _pick("有点烦人，稍微有点不爽")
    assert ctx["intensity"] <= 5, ctx


def test_moderate_anger():
    item, ctx = _pick("好气啊，真烦")
    assert 5 <= ctx["intensity"] <= 7, ctx


def test_strong_anger():
    item, ctx = _pick("我彻底气炸了，受不了了")
    assert ctx["intensity"] >= 8, ctx


def test_three_anger_levels_choose_different_stickers():
    light, lctx = _pick("有点烦人，稍微有点不爽")
    mid, mctx = _pick("好气啊，真烦")
    strong, sctx = _pick("我彻底气炸了，受不了了")
    assert lctx["intensity"] < mctx["intensity"] < sctx["intensity"]
    assert len({light["id"], mid["id"], strong["id"]}) >= 2


def test_mild_sadness_vs_strong_grief():
    mild, mild_ctx = _pick("有点委屈")
    strong, strong_ctx = _pick("我崩溃了，哭到停不下来，受不了了")
    assert mild_ctx["intensity"] <= 5 < strong_ctx["intensity"]
    assert mild["id"] != strong["id"]


def test_out_of_range_penalised(by_id):
    ctx = {"emotion": ["伤心"], "intensity": 2, "keywords": [], "actions": [], "intent": []}
    near = score_item(by_id["cat-029"], ctx)      # 4-7
    far = score_item(by_id["cat-002"], ctx)       # 7-10
    assert "intensity" in near["breakdown"]
    assert near["breakdown"]["intensity"] > far["breakdown"]["intensity"]


def test_missing_intensity_range_is_neutral_not_dropped():
    ctx = {"emotion": ["开心"], "intensity": 9, "keywords": [], "actions": [], "intent": []}
    legacy = {"id": "legacy-1", "name": "旧图", "description": "", "emotion": ["开心"],
              "tags": [], "use_when": [], "avoid_when": [], "priority": 5, "file": "stickers/x.png"}
    scored = score_item(legacy, ctx)
    assert scored["score"] > 0
    assert scored["warnings"], "缺少 intensity_range 时应给出回退说明"


def test_mood_strength_does_not_change_score(by_id):
    ctx = {"emotion": ["喜欢"], "intensity": 7, "keywords": [], "actions": [], "intent": []}
    item = dict(by_id["cat-042"])
    a = score_item(item, ctx)["score"]
    item_low = dict(item)
    item_low["mood_strength"] = 1
    b = score_item(item_low, ctx)["score"]
    assert a == b, "mood_strength 不应参与打分"


def test_priority_only_breaks_ties():
    ctx = {"emotion": ["开心"], "intensity": 5, "keywords": [], "actions": [], "intent": []}
    hi_prio_no_match = {"id": "x1", "name": "无关", "description": "", "emotion": ["生气"],
                        "tags": [], "use_when": [], "avoid_when": [], "priority": 10,
                        "file": "stickers/x1.png", "intensity_range": [4, 6]}
    lo_prio_match = {"id": "x2", "name": "开心", "description": "", "emotion": ["开心"],
                     "tags": [], "use_when": [], "avoid_when": [], "priority": 3,
                     "file": "stickers/x2.png", "intensity_range": [4, 6]}
    assert score_item(lo_prio_match, ctx)["score"] > score_item(hi_prio_no_match, ctx)["score"]
