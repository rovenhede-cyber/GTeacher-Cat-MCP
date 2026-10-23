# -*- coding: utf-8 -*-
"""R5 意图引擎：10 类意图、family、overlay 优先级、证据校验、apology 不做推导。

这些测试描述的是 R5 的契约，先于实现写下来。实现完成前它们应当失败。
"""
import json
import logging

import pytest

import intent_engine
from emotion_engine import analyze_context
from taxonomy import (
    APOLOGY_ACTION_EVIDENCE,
    ASSISTANT_INTENTS,
    BEHAVIOR_RULES,
    INTENT_CONFLICT,
    INTENT_FAMILY,
)


# ---------------------------------------------------------------- 词汇表完整性
def test_ten_assistant_intents():
    assert len(ASSISTANT_INTENTS) == 10
    assert len(set(ASSISTANT_INTENTS)) == 10


def test_every_intent_has_family_and_conflict_entry():
    for intent in ASSISTANT_INTENTS:
        assert INTENT_FAMILY.get(intent), intent
        assert intent in INTENT_CONFLICT, intent
        # 冲突表只能引用已知意图，不能写出拼错的名字
        assert set(INTENT_CONFLICT[intent]) <= set(ASSISTANT_INTENTS), intent
        assert intent not in INTENT_CONFLICT[intent], intent


def test_intent_family_groups_are_coherent():
    families = {INTENT_FAMILY[i] for i in ASSISTANT_INTENTS}
    assert {"support", "positive", "repair", "play", "align"} <= families


def test_behavior_rules_reference_known_behaviors():
    known = set(ASSISTANT_INTENTS) | {"neutral"}
    for scene, behaviors in BEHAVIOR_RULES.items():
        assert scene
        assert set(behaviors) <= known, (scene, behaviors)


# ---------------------------------------------------------------- overlay
def test_overlay_entries_have_evidence_and_source():
    overlay = intent_engine.load_overlay()
    assert overlay["schema"] == 1
    entries = overlay["stickers"]
    assert len(entries) >= 40, "overlay 覆盖太少，规则推导会承担大部分判断"
    for sticker_id, entry in entries.items():
        assert sticker_id.startswith("cat-"), sticker_id
        assert entry["behaviors"], sticker_id
        assert set(entry["behaviors"]) <= set(ASSISTANT_INTENTS), sticker_id
        assert entry["source"] == "manual", sticker_id
        assert entry["evidence"].strip(), sticker_id
        assert entry.get("persona_fit") in {"assistant", "user", "shared"}, sticker_id


def test_overlay_evidence_must_exist_in_metadata(library):
    """证据必须是图片元数据里真实存在的文本，写错直接报错（数据错误应该早暴露）。"""
    overlay = intent_engine.load_overlay()
    intent_engine.validate_overlay(overlay, library["stickers"])  # 不抛异常

    broken = {
        "schema": 1,
        "stickers": {
            "cat-002": {
                "behaviors": ["comfort"],
                "persona_fit": "assistant",
                "source": "manual",
                "evidence": "这段文字在描述里根本不存在",
            }
        },
    }
    with pytest.raises(intent_engine.OverlayError) as exc:
        intent_engine.validate_overlay(broken, library["stickers"])
    assert "cat-002" in str(exc.value)


def test_overlay_orphan_id_only_warns(library, caplog):
    """overlay 里出现图库里没有的 id：只告警，不崩。"""
    overlay = {
        "schema": 1,
        "stickers": {
            "cat-999": {
                "behaviors": ["comfort"],
                "persona_fit": "assistant",
                "source": "manual",
                "evidence": "任意",
            }
        },
    }
    with caplog.at_level(logging.WARNING, logger="GTeacherCat"):
        orphans = intent_engine.validate_overlay(overlay, library["stickers"])
    assert orphans == ["cat-999"]
    assert "cat-999" in caplog.text


def test_manual_overlay_wins_over_derived(monkeypatch):
    """manual 标注永不被规则推导覆盖（哪怕推导结果更长/更"合理"）。"""
    forced = {
        "schema": 1,
        "stickers": {
            "x-1": {
                "behaviors": ["comfort"],
                "persona_fit": "assistant",
                "source": "manual",
                "evidence": "测试用图片",
            }
        },
    }
    monkeypatch.setattr(intent_engine, "_overlay", forced, raising=False)
    item = {
        "id": "x-1",
        "name": "测试图",
        "description": "测试用图片",
        # 这些字段单独看会推导出 teasing（scene=玩笑式警告）
        "scene": ["玩笑式警告"],
        "emotion": ["嘲讽"],
        "action": ["举菜刀"],
    }
    info = intent_engine.behaviors_for(item)
    assert info["behaviors"] == ["comfort"]
    assert info["source"] == "overlay"


def test_derived_behaviors_when_no_overlay():
    item = {
        "id": "y-1",
        "name": "难过图",
        "description": "在哭",
        "scene": ["伤心"],
        "emotion": ["委屈"],
        "action": ["哭泣"],
    }
    info = intent_engine.behaviors_for(item)
    assert info["source"] == "derived"
    assert "comfort" in info["behaviors"]


def test_unknown_item_is_neutral():
    info = intent_engine.behaviors_for({"id": "z-9", "name": "?", "description": ""})
    assert info["behaviors"] == ["neutral"]
    assert info["source"] == "neutral"


# ---------------------------------------------------------------- apology 边界
def test_apology_is_not_derived_from_gratitude(library):
    """cat-035 鞠躬的语义是感谢；不因"鞠躬"像道歉就把它标成 apology。"""
    by_id = {item["id"]: item for item in library["stickers"]}
    info = intent_engine.behaviors_for(by_id["cat-035"])
    assert "gratitude" in info["behaviors"]
    assert "apology" not in info["behaviors"]


def test_no_item_is_apology_by_default(library):
    """默认图库里没有任何一张被确认为道歉动作的表情。"""
    assert "鞠躬" in APOLOGY_ACTION_EVIDENCE
    for item in library["stickers"]:
        assert "apology" not in intent_engine.behaviors_for(item)["behaviors"], item["id"]


def test_apology_is_never_derived_from_user_text():
    """助手是否需要道歉，服务端无法从用户文本推断。"""
    for text in ["对不起", "抱歉啊", "不好意思", "是我错了"]:
        assert intent_engine.derive_intent(analyze_context(text)) != "apology", text


# ---------------------------------------------------------------- 意图推导
@pytest.mark.parametrize("text,expected", [
    ("实验又失败了，好难受", "comfort"),
    ("有点委屈", "comfort"),
    ("我觉得自己很失败", "comfort"),
    ("今天好开心", "celebrate"),
    ("我拿到 offer 了！", "celebrate"),
    ("谢谢你一直帮我", "gratitude"),
    ("我爱你，媳妇～", "affection"),
    ("想亲亲你", "affection"),
    ("哈哈你怎么又迟到了，狗头", "teasing"),
    ("唉，好累", "accompany"),
])
def test_derive_intent_core_scenes(text, expected):
    assert intent_engine.derive_intent(analyze_context(text)) == expected, text


@pytest.mark.parametrize("text", [
    "我真的不想活了",
    "这个 API 报 500，怎么排查",
    "帮我写一个脚本",
])
def test_no_intent_for_crisis_or_technical(text):
    assert intent_engine.derive_intent(analyze_context(text)) is None, text


def test_no_intent_for_explicit_sticker_request():
    """用户点名要图时，选图由请求本身决定，不需要助手意图。"""
    ctx = analyze_context("给我一张生气的猫猫", explicit_request=True)
    assert intent_engine.derive_intent(ctx) is None


def test_analyze_context_exposes_assistant_intent_without_changing_old_keys():
    ctx = analyze_context("实验又失败了，好难受")
    assert ctx["assistant_intent"] == "comfort"
    # 旧键必须在且语义不变
    for key in ("emotion", "intent", "keywords", "actions", "intensity", "crisis",
                "serious", "scenes", "user_emotion", "requested_sticker_emotion",
                "explicit_sticker_request", "context_hash"):
        assert key in ctx


# ---------------------------------------------------------------- 非法值
@pytest.mark.parametrize("value,expected", [
    ("comfort", "comfort"),
    ("  COMFORT ", "comfort"),
    ("apology", "apology"),
    ("", None),
    (None, None),
    ("nonsense", None),
    ("comfort; drop table", None),
])
def test_normalize_intent(value, expected):
    assert intent_engine.normalize_intent(value) == expected


# ---------------------------------------------------------------- 标注文件损坏时的降级
def test_disable_overlay_falls_back_to_derived(by_id):
    """标注被禁用后，行为改为规则推导，而不是继续抛错。"""
    import sticker_engine

    try:
        intent_engine.disable_overlay("test")
        info = intent_engine.behaviors_for(by_id["cat-049"])
        assert info["source"] in {"derived", "neutral"}
        # 推导永不到 apology：cat-035 只能被推成 gratitude 或 neutral
        assert "apology" not in intent_engine.behaviors_for(by_id["cat-035"])["behaviors"]
        # 图库仍然可用来选图
        assert sticker_engine.search_sticker(
            analyze_context("抱抱我"), relationship="intimate", deterministic=True) is not None
    finally:
        intent_engine.reset_overlay()


def test_corrupt_overlay_degrades_instead_of_blocking_library(monkeypatch, library, caplog):
    """overlay 校验失败时，图库仍能加载（否则 off 回滚也失效）。"""
    import sticker_engine

    def boom(*a, **k):
        raise intent_engine.OverlayError("simulated corrupt overlay")

    monkeypatch.setattr(intent_engine, "validate_overlay", boom)

    class Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return library

    monkeypatch.setattr(sticker_engine.requests, "get", lambda *a, **k: Resp())
    monkeypatch.setattr(sticker_engine, "_library_cache", None, raising=False)
    try:
        with caplog.at_level(logging.ERROR, logger="GTeacherCat"):
            data = sticker_engine.load_library(force_refresh=True)
        assert len(data["stickers"]) == len(library["stickers"])
        assert "intent_overlay" in caplog.text
        # 降级后行为来自推导，不是 overlay
        assert intent_engine.behaviors_for(library["stickers"][0])["source"] != "overlay"
    finally:
        monkeypatch.undo()          # 先还原 validate_overlay，再注入图库
        intent_engine.reset_overlay()
        sticker_engine.set_library(library)
