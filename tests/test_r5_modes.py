# -*- coding: utf-8 -*-
"""R5 三模式：off / shadow / auto。

契约：
- off    = R4 原路径，完全不看意图
- shadow = 算出 R5 结果只写日志，**返回仍是 R4 结果**
- auto   = 意图生效
默认值是 shadow（先观察，验收后再切 auto）。
"""
import logging
import os

import pytest

import sticker_engine
from emotion_engine import analyze_context
from sticker_config import CONFIG, reset_config

# 一个不依赖真实图库的场景：A 靠情绪命中，B 靠意图命中
SyntheticLibrary = {
    "version": "synthetic-r5",
    "stickers": [
        # 只靠情绪命中：scene 是"平静"，推导不出 gratitude
        {"id": "emo-1", "name": "情绪图", "description": "表达感谢的图", "emotion": ["感谢"],
         "tags": [], "use_when": [], "avoid_when": [], "action": ["微笑"], "scene": ["平静"],
         "priority": 9, "file": "stickers/emo-1.png", "intensity_range": [4, 7]},
        {"id": "intent-1", "name": "意图图", "description": "道谢鞠躬", "emotion": ["平静"],
         "tags": [], "use_when": [], "avoid_when": [], "action": ["鞠躬"], "scene": ["感谢"],
         "priority": 5, "file": "stickers/intent-1.png", "intensity_range": [4, 7]},
    ],
}

INTENT_CONTEXT = {
    "emotion": ["感谢"],
    "intensity": 5,
    "keywords": [],
    "actions": [],
    "intent": ["gratitude"],
    # 不设 scenes：否则 R4 的 scene_hit 会先把"意图图"选出来，看不出意图项的作用
    "scenes": [],
    "assistant_intent": "gratitude",
    "explicit_sticker_request": False,
    "context_hash": "deadbeefdeadbeef",
}


@pytest.fixture()
def mode(monkeypatch):
    def _set(value):
        monkeypatch.setattr(CONFIG, "intent_mode", value)
    return _set


@pytest.fixture()
def synthetic():
    sticker_engine.set_library(SyntheticLibrary)
    return SyntheticLibrary


# ---------------------------------------------------------------- 默认值 / 合法值
def test_default_mode_is_shadow():
    assert CONFIG.intent_mode == "shadow"


def test_mode_values_are_only_three():
    assert set(sticker_engine.INTENT_MODES) == {"off", "shadow", "auto"}


def test_invalid_env_mode_falls_back_to_shadow(monkeypatch):
    monkeypatch.setenv("R5_INTENT_MODE", "turbo")
    reset_config()
    try:
        assert CONFIG.intent_mode == "shadow"
    finally:
        monkeypatch.delenv("R5_INTENT_MODE", raising=False)
        reset_config()


def test_env_mode_is_respected(monkeypatch):
    monkeypatch.setenv("R5_INTENT_MODE", "auto")
    reset_config()
    try:
        assert CONFIG.intent_mode == "auto"
    finally:
        monkeypatch.delenv("R5_INTENT_MODE", raising=False)
        reset_config()


# ---------------------------------------------------------------- off
def test_off_ignores_assistant_intent(mode, synthetic):
    mode("off")
    without = sticker_engine.search_sticker(dict(INTENT_CONTEXT), deterministic=True)
    with_intent = dict(INTENT_CONTEXT, assistant_intent="gratitude")
    assert sticker_engine.search_sticker(with_intent, deterministic=True)["id"] == without["id"]
    assert without["id"] == "emo-1"


def test_off_does_not_score_intent(mode, synthetic):
    mode("off")
    row = sticker_engine.score_item(synthetic["stickers"][1], dict(INTENT_CONTEXT))
    assert "intent_exact" not in row["breakdown"]
    assert "intent_family" not in row["breakdown"]


# ---------------------------------------------------------------- shadow
def test_shadow_computes_but_returns_r4_result(mode, synthetic):
    mode("off")
    r4 = sticker_engine.search_sticker(dict(INTENT_CONTEXT), deterministic=True)["id"]
    mode("shadow")
    shadow = sticker_engine.search_sticker(dict(INTENT_CONTEXT), deterministic=True)["id"]
    assert shadow == r4 == "emo-1"


def test_shadow_logs_would_be_choice(mode, synthetic, caplog):
    mode("shadow")
    with caplog.at_level(logging.INFO, logger="GTeacherCat"):
        sticker_engine.search_sticker(dict(INTENT_CONTEXT), deterministic=True)
    assert "r5_mode=shadow" in caplog.text
    assert "r5_shadow_intent=gratitude" in caplog.text
    assert "r5_shadow_id=intent-1" in caplog.text


def test_shadow_same_as_off_on_real_library(mode):
    texts = [
        "实验又失败了，好难受",
        "有点委屈",
        "哈哈你怎么又迟到了，狗头",
        "我拿到 offer 了！",
        "谢谢你一直帮我",
        "唉，好累",
        "抱抱我",
        "论文写不出来，好崩溃",
        "我想撒娇",
        "今天好开心",
    ]
    mode("off")
    off_ids = [sticker_engine.search_sticker(analyze_context(t), relationship="intimate",
                                             deterministic=True) for t in texts]
    mode("shadow")
    shadow_ids = [sticker_engine.search_sticker(analyze_context(t), relationship="intimate",
                                                deterministic=True) for t in texts]
    assert [x["id"] if x else None for x in off_ids] == [x["id"] if x else None for x in shadow_ids]


# ---------------------------------------------------------------- auto
def test_auto_lets_intent_change_the_choice(mode, synthetic):
    mode("auto")
    picked = sticker_engine.search_sticker(dict(INTENT_CONTEXT), deterministic=True)
    assert picked["id"] == "intent-1"


def test_auto_scores_intent_exact_and_reduces_emotion_weight(mode, synthetic):
    mode("auto")
    emotion_only = sticker_engine.score_item(synthetic["stickers"][0], dict(INTENT_CONTEXT))
    intent_match = sticker_engine.score_item(synthetic["stickers"][1], dict(INTENT_CONTEXT))
    assert emotion_only["breakdown"]["emotion_group"] == CONFIG.emotion_when_intent
    assert intent_match["breakdown"]["intent_exact"] == CONFIG.intent_exact
    assert intent_match["breakdown"]["intent_persona"] == CONFIG.intent_persona


def test_auto_logs_mode_and_intent(mode, synthetic, caplog):
    mode("auto")
    with caplog.at_level(logging.INFO, logger="GTeacherCat"):
        sticker_engine.search_sticker(dict(INTENT_CONTEXT), deterministic=True)
    assert "r5_mode=auto" in caplog.text
    assert "assistant_intent=gratitude" in caplog.text
    assert "r5_shadow_id=" not in caplog.text


# ---------------------------------------------------------------- 日志脱敏
@pytest.mark.parametrize("value", ["off", "shadow", "auto"])
def test_logs_never_contain_raw_conversation(mode, value, caplog):
    mode(value)
    text = "我今天被领导骂了，好委屈，顺便我的手机号是 13800000000"
    with caplog.at_level(logging.DEBUG, logger="GTeacherCat"):
        sticker_engine.search_sticker(analyze_context(text), relationship="intimate",
                                      deterministic=True)
    assert text not in caplog.text
    assert "13800000000" not in caplog.text
    assert "context_hash=" in caplog.text or "trigger_result" in caplog.text
