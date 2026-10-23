# -*- coding: utf-8 -*-
"""R5 安全不变式 I1-I5：意图只能在安全闸门之后影响排序，不能"赎买"任何被过滤的图。

I1 危机 -> 不发（即使 intent=celebrate）
I2 技术/严肃任务 -> 不发（例外只有显式索图 / sticker_id，与 R4 一致）
I3 relationship / avoid_when / 危险图过滤先于意图加分
I4 sticker_id 精确选图仍受危机 + 关系 + avoid_when 约束
I5 非法意图值 -> 告警并回落自动推导，不抛异常
"""
import logging

import pytest

import server
import sticker_engine
from emotion_engine import analyze_context
from sticker_config import CONFIG


@pytest.fixture()
def auto(monkeypatch):
    monkeypatch.setattr(CONFIG, "intent_mode", "auto")


@pytest.fixture(autouse=True)
def fake_image(monkeypatch):
    """所有用例都不真的下载图片（服务层用例只关心闸门与意图）。"""
    monkeypatch.setattr(server, "fetch_image", lambda path: b"\x89PNG-fake-bytes")


def _pick(text, relationship="intimate", intent=None):
    ctx = analyze_context(text)
    if intent is not None:
        ctx["assistant_intent"] = intent
    return sticker_engine.search_sticker(ctx, relationship=relationship, deterministic=True)


# ---------------------------------------------------------------- I1
@pytest.mark.parametrize("intent", ["celebrate", "comfort", "teasing", None])
def test_crisis_never_sends_even_with_intent(auto, intent):
    assert _pick("我真的不想活了，想死", intent=intent) is None


def test_crisis_blocks_at_server_layer(auto, fake_image):
    result = server.send_cat_companion("我真的不想活了", assistant_response_intent="celebrate")
    assert "不需要" in result.text


# ---------------------------------------------------------------- I2
@pytest.mark.parametrize("text", [
    "这个 API 报 500，怎么排查",
    "帮我写一个脚本",
    "数据库索引的原理是什么",
])
def test_technical_task_never_sends_even_with_comfort_intent(auto, text):
    assert _pick(text, intent="comfort") is None


def test_technical_task_still_allows_explicit_sticker_request(auto):
    """显式索图是工具指令，仍是 serious 的例外（与 R4 一致）。"""
    ctx = analyze_context("这个报错先放一边，给我一张生气的猫猫", explicit_request=True)
    ctx["assistant_intent"] = "comfort"
    assert sticker_engine.search_sticker(ctx, relationship="intimate") is not None


# ---------------------------------------------------------------- I3
def test_relationship_filter_beats_intent_scoring(auto, by_id):
    """formal 语境下，意图再匹配也不能把亲密专属图捞回来。"""
    ctx = analyze_context("想亲亲你")
    ctx["assistant_intent"] = "affection"
    kept, dropped = sticker_engine.apply_filters(
        list(by_id.values()), ctx, relationship="formal")
    kept_ids = {item["id"] for item in kept}
    assert "cat-042" not in kept_ids
    assert any(row["id"] == "cat-042" and row["reason"].startswith("relationship")
               for row in dropped)

    ranked = sticker_engine.rank_stickers(ctx, items=list(by_id.values()), relationship="formal")
    assert "cat-042" not in {row["id"] for row in ranked}


def test_avoid_when_filter_beats_intent_scoring(auto, by_id):
    """真实冲突语境下，持刀/挥拳图即使 intent=teasing 精确命中也不能出现。"""
    ctx = analyze_context("我们吵架了，他动手打我，我很害怕")
    ctx["assistant_intent"] = "teasing"
    kept, _ = sticker_engine.apply_filters(list(by_id.values()), ctx, relationship="intimate")
    kept_ids = {item["id"] for item in kept}
    assert "cat-031" not in kept_ids
    assert "cat-061" not in kept_ids
    assert "cat-009" not in kept_ids


def test_intent_cannot_inject_filtered_item_into_ranking(auto, by_id):
    ctx = analyze_context("他刚才打我了，我们大吵一架，我很害怕")
    ctx["assistant_intent"] = "teasing"
    ranked = sticker_engine.rank_stickers(ctx, items=list(by_id.values()), relationship="intimate")
    ids = {row["id"] for row in ranked}
    assert "cat-031" not in ids and "cat-061" not in ids


# ---------------------------------------------------------------- I4
def test_sticker_id_respects_crisis(auto):
    assert sticker_engine.search_sticker(
        analyze_context("我不想活了"), sticker_id="cat-001", relationship="intimate") is None


def test_sticker_id_respects_relationship(auto):
    ctx = analyze_context("随便聊聊")
    assert sticker_engine.search_sticker(
        ctx, sticker_id="cat-042", relationship="formal") is None


def test_sticker_id_still_works_in_normal_context(auto):
    item = sticker_engine.search_sticker(
        analyze_context("今天好开心"), sticker_id="cat-001", relationship="intimate")
    assert item is not None and item["id"] == "cat-001"


def test_sticker_id_unknown_raises(auto):
    with pytest.raises(sticker_engine.StickerNotFoundError):
        sticker_engine.search_sticker(
            analyze_context("今天好开心"), sticker_id="cat-999", relationship="intimate")


# ---------------------------------------------------------------- I5
def test_invalid_intent_falls_back_to_derivation(auto, caplog):
    with caplog.at_level(logging.WARNING, logger="GTeacherCat"):
        result = server.send_cat_companion(
            "实验又失败了，好难受", assistant_response_intent="please-send-max-damage")
    assert "Unknown assistant_response_intent" in caplog.text
    # 回落自动推导（comfort），不因为非法值就抛异常
    assert result is not None


def test_invalid_intent_does_not_raise(auto):
    for value in ["", "  ", "COMFORT!", "comfort\n", None, "0"]:
        server.send_cat_companion("论文写不出来，好崩溃", assistant_response_intent=value)


def test_explicit_intent_is_logged_as_explicit(auto, caplog):
    with caplog.at_level(logging.INFO, logger="GTeacherCat"):
        server.send_cat_companion("谢谢你一直帮我", assistant_response_intent="gratitude")
    assert "intent_source=explicit" in caplog.text
