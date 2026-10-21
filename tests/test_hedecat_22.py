"""Local, network-free semantic sticker matching regression tests."""

import copy
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import emotion_engine
import sticker_engine
import trigger_engine


@pytest.fixture
def library(monkeypatch):
    data = json.loads((Path(__file__).parent / "fixtures" / "instructions_v22.json")
                      .read_text(encoding="utf-8"))
    monkeypatch.setattr(sticker_engine, "load_library", lambda **kwargs: data)
    return data


def pick(text, *, deterministic=True):
    context = emotion_engine.analyze_context(text)
    assert trigger_engine.should_send_sticker(context)
    return sticker_engine.search_sticker(context, deterministic=deterministic)


def test_generic_angry_request(library):
    result = pick("给我一张生气的猫猫")
    assert "生气" in result["emotion"]


@pytest.mark.parametrize("text,expected", [
    ("给我一张有点生气的猫猫", "cat-026"),
    ("给我一张特别生气的猫猫", "cat-009"),
])
def test_angry_strength(library, text, expected):
    assert pick(text)["id"] == expected


@pytest.mark.parametrize("wording", ["头顶冒火", "脑袋着火", "气得冒烟", "头上有火焰"])
def test_fire_synonyms_filter_visual_candidates(library, wording):
    result = pick(f"给我一张{wording}的猫猫")
    assert result["id"] in {"cat-008", "cat-009"}


def test_fist_and_collar(library):
    assert pick("给我一张挥拳头的生气猫猫")["id"] == "cat-009"
    assert pick("给我一张揪衣领的猫猫")["id"] == "cat-026"


def test_heart_hug(library):
    assert pick("给我一张抱爱心的猫猫")["id"] == "cat-010"


def test_affection_and_celebration_remain(library):
    assert pick("宝宝亲亲！")["id"] == "cat-025"
    assert pick("我今天实验成功啦！")["id"] == "cat-020"


def test_requested_emotion_is_not_user_emotion(library):
    context = emotion_engine.analyze_context("给我一张生气表情包，但我本人没生气")
    assert context["user_emotion"] == []
    assert context["requested_sticker_emotion"] == ["angry"]
    assert sticker_engine.search_sticker(context)["id"] in {
        "cat-008", "cat-009", "cat-026", "cat-031", "cat-032", "cat-038"
    }


def test_vocative_and_following_qualifier_do_not_turn_anger_into_love(library):
    context = emotion_engine.analyze_context(
        "宝宝，请发一张生气的猫猫表情包，普通程度的生气。"
    )
    assert context["user_emotion"] == []
    assert context["requested_sticker_emotion"] == ["angry"]
    assert context["intensity"] == 5
    assert "生气" in sticker_engine.search_sticker(context, deterministic=True)["emotion"]


@pytest.mark.parametrize("wording,expected", [
    ("宝宝，请发一张有点生气的猫猫表情包。", "cat-026"),
    ("宝宝，请发一张特别生气的猫猫表情包。", "cat-009"),
])
def test_vocative_does_not_break_light_or_strong_anger(library, wording, expected):
    assert pick(wording)["id"] == expected


def test_user_mood_before_request_does_not_change_requested_intensity(library):
    context = emotion_engine.analyze_context("我气死了，请发一张有点生气的猫猫")
    assert context["user_emotion"] == ["angry"]
    assert context["requested_sticker_emotion"] == ["angry"]
    assert context["intensity"] <= 3
    assert sticker_engine.search_sticker(context, deterministic=True)["id"] == "cat-026"


@pytest.mark.parametrize("text,low,high", [
    ("我有点生气", 1, 3),
    ("我真的很生气", 4, 7),
    ("我真的气死了！！", 8, 10),
    ("我有点难过", 1, 3),
    ("我非常开心！！", 8, 10),
    ("我有点害羞", 1, 3),
])
def test_strength_is_cue_based_across_emotions(text, low, high):
    level = emotion_engine.analyze_context(text)["intensity"]
    assert low <= level <= high


def test_repetition_increases_strength_without_punctuation_alone():
    plain = emotion_engine.analyze_context("我生气了")["intensity"]
    repeated = emotion_engine.analyze_context("我生气生气了")["intensity"]
    punctuated = emotion_engine.analyze_context("我生气了！！！")["intensity"]
    assert repeated > plain
    assert punctuated <= plain + 1


def test_legacy_json_without_intensity_range(library, monkeypatch):
    legacy = copy.deepcopy(library)
    for item in legacy["stickers"]:
        item.pop("intensity_range", None)
    monkeypatch.setattr(sticker_engine, "load_library", lambda **kwargs: legacy)
    assert pick("给我一张特别生气的猫猫") is not None


def test_unavailable_visual_feature_has_safe_no_match(library):
    assert pick("给我一张摸头的猫猫") is None


def test_random_choice_never_crosses_visual_constraint(library):
    context = emotion_engine.analyze_context("给我一张头顶冒火的猫猫")
    with patch.object(sticker_engine.random, "choice", side_effect=lambda items: items[-1]):
        assert all(sticker_engine.search_sticker(context)["id"] in {"cat-008", "cat-009"}
                   for _ in range(20))


def test_deterministic_tie_break(library):
    context = emotion_engine.analyze_context("给我一张头顶冒火的猫猫")
    assert {sticker_engine.search_sticker(context, deterministic=True)["id"]
            for _ in range(10)} == {"cat-008"}


def test_remote_index_failure_is_explicit(monkeypatch):
    monkeypatch.setattr(sticker_engine, "_library_cache", None)
    with patch.object(sticker_engine.requests, "get", side_effect=requests.RequestException("offline")):
        with pytest.raises(requests.RequestException, match="offline"):
            sticker_engine.load_library(force_refresh=True)
