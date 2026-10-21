"""候选过滤：avoid_when 语境排除、relationship 关系限制、危险图保守回退。"""
from emotion_engine import analyze_context
from sticker_engine import apply_filters, select_sticker


def test_intimate_sticker_blocked_without_relationship(by_id):
    ctx = analyze_context("爱你，媳妇～")
    kept, dropped = apply_filters(list(by_id.values()), ctx, relationship="unknown")
    kept_ids = {x["id"] for x in kept}
    assert "cat-042" not in kept_ids, "缺少关系上下文时不应保留带「媳妇」称呼的图"
    assert any(d["id"] == "cat-042" for d in dropped)


def test_intimate_sticker_allowed_with_intimate_relationship(by_id):
    ctx = analyze_context("爱你，媳妇～")
    kept, _ = apply_filters(list(by_id.values()), ctx, relationship="intimate")
    assert "cat-042" in {x["id"] for x in kept}


def test_explicit_unknown_never_returns_intimate_sticker():
    """默认语境是 intimate；只有显式 unknown 时才排除亲密专属图。"""
    item = select_sticker("我爱你，媳妇～", relationship="unknown")
    assert item is not None
    assert item["id"] != "cat-042", item["id"]


def test_avoid_when_conflict_excludes_weapon_stickers(by_id):
    ctx = analyze_context("他刚才打我了，我们大吵一架，我很害怕")
    kept, dropped = apply_filters(list(by_id.values()), ctx, relationship="unknown")
    kept_ids = {x["id"] for x in kept}
    dropped_ids = {x["id"] for x in dropped}
    assert "cat-031" not in kept_ids, "持刀图不应出现在真实冲突/恐惧语境"
    assert "cat-061" not in kept_ids
    assert {"cat-031", "cat-061"} & dropped_ids


def test_strong_anger_sticker_excluded_in_real_conflict(by_id):
    ctx = analyze_context("我们现在在吵架，他情绪很激动，快打起来了")
    kept, _ = apply_filters(list(by_id.values()), ctx, relationship="unknown")
    kept_ids = {x["id"] for x in kept}
    assert "cat-009" not in kept_ids, "挥拳生气图不应出现在真实冲突语境"


def test_serious_context_excludes_playful_anger(by_id):
    ctx = analyze_context("这个项目明天要正式汇报，我现在很焦虑")
    ctx["serious"] = True
    kept, _ = apply_filters(list(by_id.values()), ctx, relationship="unknown")
    kept_ids = {x["id"] for x in kept}
    assert "cat-061" not in kept_ids


def test_benign_context_keeps_weapon_sticker(by_id):
    """纯玩笑语境下，持刀图仍可参与（只是 priority 很低）。"""
    ctx = analyze_context("哈哈你怎么又迟到了，狗头")
    kept, _ = apply_filters(list(by_id.values()), ctx, relationship="unknown")
    assert "cat-031" in {x["id"] for x in kept}


def test_filter_does_not_drop_everything(by_id):
    ctx = analyze_context("今天好累啊")
    kept, _ = apply_filters(list(by_id.values()), ctx, relationship="unknown")
    assert len(kept) > 60, len(kept)


# ---------------------------------------------------------------- 关系矩阵
import pytest  # noqa: E402


@pytest.mark.parametrize(
    "relationship, expected",
    [
        # 041/043 声明 ["朋友","亲密关系"]，042 声明 ["亲密关系","亲昵角色扮演"]
        ("intimate", {"cat-041", "cat-042", "cat-043"}),
        ("friend", {"cat-041", "cat-043"}),
        ("formal", set()),          # 正式语境不放行任何带关系声明的图片
        ("unknown", {"cat-041", "cat-043"}),
    ],
)
def test_relationship_matrix(by_id, relationship, expected):
    ctx = analyze_context("今天有点累")
    kept, dropped = apply_filters(list(by_id.values()), ctx, relationship=relationship)
    ids = {x["id"] for x in kept}

    declared = {"cat-041", "cat-042", "cat-043"}
    assert declared & ids == expected, (relationship, sorted(declared & ids))
    assert "cat-001" in ids, "通用图片（无 relationship 字段）在任何关系下都应保留"
    assert all("relationship" not in d["reason"] for d in dropped if d["id"] == "cat-001")


def test_formal_context_drops_friend_only_images(by_id):
    """正式语境不应自动允许「仅朋友」的图片，但通用图照常可选。"""
    ctx = analyze_context("今天有点累")
    kept, _ = apply_filters(list(by_id.values()), ctx, relationship="formal")
    ids = {x["id"] for x in kept}
    assert "cat-041" not in ids
    assert "cat-043" not in ids
    assert len(ids) > 60
