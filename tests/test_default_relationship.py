"""默认关系语境 = intimate（HedeCat 日常聊天场景）；unknown 只能显式指定。"""
import os

import pytest

from emotion_engine import analyze_context
from sticker_config import CONFIG, reload_config, reset_config
from sticker_engine import (
    apply_filters,
    rank_stickers,
    resolve_relationship,
    select_sticker,
)


@pytest.fixture()
def restore_default_relationship():
    yield
    os.environ.pop("DEFAULT_RELATIONSHIP_CONTEXT", None)
    reset_config()


# ---------------------------------------------------------------- 默认值
def test_default_relationship_is_intimate():
    assert CONFIG.default_relationship == "intimate"
    assert resolve_relationship(None) == "intimate"
    assert resolve_relationship("") == "intimate"
    assert resolve_relationship("default") == "intimate"


def test_unknown_is_not_the_default():
    """unknown 只在显式要求时生效，不能成为正常聊天缺省值。"""
    assert resolve_relationship("unknown") == "unknown"
    assert CONFIG.default_relationship != "unknown"


def test_invalid_relationship_falls_back_to_default():
    assert resolve_relationship("cousin") == "intimate"


def test_env_override_switches_default(tmp_path, restore_default_relationship):
    env_file = tmp_path / ".env"
    env_file.write_text("DEFAULT_RELATIONSHIP_CONTEXT=friend\n", encoding="utf-8")
    reload_config(str(env_file))
    assert CONFIG.default_relationship == "friend"
    assert resolve_relationship(None) == "friend"
    # 显式传参仍可覆盖默认值
    assert resolve_relationship("intimate") == "intimate"


# ---------------------------------------------------------------- 默认亲密召回
@pytest.mark.parametrize(
    "text, expected",
    [
        ("抱抱我", {"cat-005", "cat-025"}),
        ("想亲亲你", {"cat-025", "cat-042"}),
        ("给你比心", {"cat-010", "cat-016"}),
        ("我想撒娇", {"cat-050", "cat-042", "cat-007"}),
    ],
)
def test_default_intimate_recalls_affection_stickers(text, expected):
    item = select_sticker(analyze_context(text))  # 不传 relationship
    assert item is not None, text
    assert item["id"] in expected, (text, item["id"])


def test_exclusive_intimate_sticker_selectable_by_default(by_id):
    """cat-042「媳妇～」声明只属于亲密关系，默认 intimate 下应进入候选。"""
    ctx = analyze_context("我想撒娇")
    ids = [row["id"] for row in rank_stickers(ctx, items=list(by_id.values()))]
    assert "cat-042" in ids


# ---------------------------------------------------------------- 显式覆盖
def test_explicit_formal_excludes_intimate_only(by_id):
    ctx = analyze_context("我想撒娇")
    kept, _ = apply_filters(list(by_id.values()), ctx, relationship="formal")
    ids = {x["id"] for x in kept}
    assert "cat-042" not in ids, "正式语境不能出现亲密专属图片"
    assert {"cat-041", "cat-043"} & ids == set(), "带关系声明的图片在 formal 下一律不出现"
    assert "cat-001" in ids, "没有 relationship 字段的通用图片不受影响"


def test_explicit_friend_excludes_intimate_only(by_id):
    ctx = analyze_context("我想撒娇")
    kept, _ = apply_filters(list(by_id.values()), ctx, relationship="friend")
    ids = {x["id"] for x in kept}
    assert "cat-042" not in ids
    assert "cat-041" in ids and "cat-043" in ids


def test_explicit_unknown_still_filters_exclusive(by_id):
    ctx = analyze_context("我想撒娇")
    ids = [row["id"] for row in rank_stickers(ctx, items=list(by_id.values()), relationship="unknown")]
    assert "cat-042" not in ids


# ---------------------------------------------------------------- 安全边界
def test_intimate_does_not_bypass_crisis(library):
    assert select_sticker("我真的不想活了", relationship="intimate") is None


def test_intimate_does_not_bypass_conflict_filter(by_id):
    ctx = analyze_context("我们现在在吵架，他动手了，我很害怕")
    kept, dropped = apply_filters(list(by_id.values()), ctx, relationship="intimate")
    ids = {x["id"] for x in kept}
    assert "cat-031" not in ids and "cat-061" not in ids
    assert "cat-009" not in ids
    reasons = {d["id"]: d["reason"] for d in dropped}
    assert {"cat-031", "cat-061", "cat-009"} <= set(reasons)
    assert reasons["cat-031"].startswith(("avoid_when", "dangerous_context"))
    assert reasons["cat-009"].startswith("avoid_when")


def test_intimate_keeps_generic_images(by_id):
    ctx = analyze_context("今天有点累")
    kept, _ = apply_filters(list(by_id.values()), ctx, relationship="intimate")
    assert len(kept) > 70, len(kept)
    assert "cat-001" in {x["id"] for x in kept}
