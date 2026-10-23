# -*- coding: utf-8 -*-
"""R5 语义正确性：助手回应意图是否让"发哪张图"更贴合。

每条期望值都来自图片 description 的实际内容（见 tests/fixtures/instructions.json）：
1. 实验又失败了，好难受   -> 需要"陪着你难过"的图（哭/低落），不是"贴贴撒娇"
2. 有点委屈               -> 同上，但强度低，不该选强度 8-10 的嚎哭图
3. 我觉得自己很失败        -> 安慰，不是比心
4. 哈哈你怎么又迟到了，狗头 -> 打趣/玩笑式嫌弃，不是"对勾认可"
5. 我拿到 offer 了！       -> 庆祝/赞赏
6. 谢谢你一直帮我          -> 感谢鞠躬
7. 抱抱我                  -> 亲密/撒娇
8. 求婚                   -> 求婚图
9. 唉，好累                -> 陪伴（一起摆烂），不是庆祝
10. 道歉意图               -> 图库没有合格道歉图，返回 None（不拿感谢图顶替）
11. 论文写不出来，好崩溃    -> 安慰
12. friend 关系 + 想亲亲你  -> 不能出现亲密专属图（cat-042）
"""
import pytest

import sticker_engine
from emotion_engine import analyze_context
from sticker_config import CONFIG

COMFORT_IDS = {"cat-002", "cat-029", "cat-054", "cat-073", "cat-068", "cat-077", "cat-036"}
TEASING_IDS = {"cat-026", "cat-031", "cat-048", "cat-061", "cat-062"}
CELEBRATE_IDS = {"cat-020", "cat-039", "cat-067", "cat-074", "cat-044", "cat-030"}
ACCOMPANY_IDS = {"cat-021", "cat-060", "cat-075", "cat-057", "cat-059", "cat-068",
                 "cat-070", "cat-051", "cat-012", "cat-047", "cat-077"}
AFFECTION_IDS = {"cat-005", "cat-025", "cat-049", "cat-010", "cat-016", "cat-042", "cat-041"}


@pytest.fixture()
def auto(monkeypatch):
    monkeypatch.setattr(CONFIG, "intent_mode", "auto")


def _pick(text, relationship="intimate"):
    return sticker_engine.search_sticker(analyze_context(text), relationship=relationship,
                                         deterministic=True)


@pytest.mark.parametrize("text,allowed,label", [
    ("哈哈你怎么又迟到了，狗头", TEASING_IDS, "打趣"),
    ("我拿到 offer 了！", CELEBRATE_IDS, "庆祝"),
    ("谢谢你一直帮我", {"cat-035"}, "感谢"),
    ("唉，好累", ACCOMPANY_IDS, "陪伴"),
    ("抱抱我", AFFECTION_IDS, "亲密"),
    ("我要单膝跪地求婚，把戒指给你", {"cat-006"}, "求婚"),
])
def test_auto_mode_semantics(auto, text, allowed, label):
    item = _pick(text)
    assert item is not None, text
    assert item["id"] in allowed, (label, text, item["id"], item["name"])


NONSENSE_FOR_COMFORT = {"cat-020", "cat-039", "cat-067", "cat-074", "cat-062", "cat-019"}


@pytest.mark.parametrize("text", [
    "实验又失败了，好难受",
    "有点委屈",
    "我觉得自己很失败",
    "论文写不出来，好崩溃",
])
def test_comfort_cases_pick_a_comfort_behavior(auto, text):
    """难过场景：选中的图必须真的在"安慰"（共情/陪着/抱抱都算），
    不能是庆祝、打趣这类明显不合时宜的表达。"""
    item = _pick(text)
    assert item is not None, text
    behaviors = sticker_engine.intent_engine.behaviors_for(item)["behaviors"]
    assert "comfort" in behaviors, (text, item["id"], item["name"], behaviors)
    assert item["id"] not in NONSENSE_FOR_COMFORT, (text, item["id"])


def test_apology_returns_none_not_a_thanks_sticker(auto, caplog):
    """道歉意图 + 没有道歉图 -> None，并且日志说明原因（不静默换成别的图）。"""
    import logging

    ctx = analyze_context("抱歉，是我没理解对，让你难受了")
    ctx["assistant_intent"] = "apology"   # 调用方明确说明"这条回复是道歉"
    with caplog.at_level(logging.INFO, logger="GTeacherCat"):
        item = sticker_engine.search_sticker(ctx, relationship="intimate", deterministic=True)
    assert item is None
    assert "fallback_reason=apology_no_candidate" in caplog.text


def test_apology_with_manual_annotation_can_be_selected(auto, monkeypatch):
    """一旦人工把某张图标成 apology，apology 才可能有候选——但默认没有这种标注。"""
    import intent_engine

    overlay = {
        "schema": 1,
        "stickers": {
            "cat-035": {
                "behaviors": ["gratitude", "apology"],
                "persona_fit": "assistant",
                "source": "manual",
                "evidence": "白色小猫弯眼微笑、微微鞠躬",
            }
        },
    }
    monkeypatch.setattr(intent_engine, "_overlay", overlay, raising=False)
    ctx = analyze_context("抱歉，是我没理解对，让你难受了")
    ctx["assistant_intent"] = "apology"
    item = sticker_engine.search_sticker(ctx, relationship="intimate", deterministic=True)
    assert item is not None and item["id"] == "cat-035"


def test_no_implicit_apology_to_comfort_mapping(auto):
    """道歉意图不允许隐式映射到 comfort：没有 apology 候选就返回 None。"""
    import intent_engine

    assert "comfort" not in intent_engine.APOLOGY_FALLBACK_BEHAVIORS
    ctx = analyze_context("抱歉")
    ctx["assistant_intent"] = "apology"
    assert sticker_engine.search_sticker(ctx, relationship="intimate", deterministic=True) is None


def test_friend_relationship_still_excludes_exclusive_intimate(auto):
    item = _pick("想亲亲你", relationship="friend")
    assert item is not None
    assert item["id"] != "cat-042"


def test_auto_does_not_break_same_input_same_result(auto):
    ids = {_pick("实验又失败了，好难受")["id"] for _ in range(5)}
    assert len(ids) == 1, ids
