"""Regression cases from actual client summaries; no live network calls."""

import json
import logging
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import emotion_engine
import server
import sticker_engine
import trigger_engine


def summary(emotion):
    return f"用户明确要求通过插件发送一张表达“{emotion}”的猫猫表情包，三个等级要分别匹配。"


@pytest.fixture
def live_index(monkeypatch):
    data = json.loads((Path(__file__).parent / "fixtures" / "instructions_v21.json")
                      .read_text(encoding="utf-8"))
    monkeypatch.setattr(sticker_engine, "load_library", Mock(return_value=data))
    # R3 起图片下载走 sticker_engine.fetch_image（server 通过 from ... import 引用），
    # 不再在 server 里直接 requests.get；所以要 mock 真实使用的下载函数本身。
    monkeypatch.setattr(server, "fetch_image", Mock(return_value=b"offline image"))
    return data


def returned_sticker(text, data, explicit=True):
    result = server.send_cat_companion(user_emotional_context=text, explicit_request=explicit)
    assert isinstance(result, list), getattr(result, "text", result)
    selected_id = re.search(r"cat-\d{3}", result[0].text).group()
    item = next(item for item in data["stickers"] if item["id"] == selected_id)
    assert item["name"] in result[0].text
    assert item["description"] in result[0].text
    assert result[0].text.endswith("/" + item["file"])
    assert server.fetch_image.call_args.args[0] == item["file"]
    return item


@pytest.mark.parametrize("emotion", ["生气", "有点生气", "特别生气"])
def test_exact_client_summary_never_selects_praise(live_index, emotion):
    assert "生气" in returned_sticker(summary(emotion), live_index)["emotion"]


@pytest.mark.parametrize("text", ["通过插件", "通过工具", "通过 MCP", "通过接口"])
def test_delivery_method_is_not_a_success_event(text):
    context = emotion_engine.analyze_context(text + "发送生气表情包")
    assert "celebrate" not in context["intent"]
    assert "happy" not in context["emotion"]


@pytest.mark.parametrize("emotion,label", [
    ("生气", "angry"), ("难过", "sad"), ("开心", "happy"),
    ("害羞", "shy"), ("喜欢", "love"),
])
def test_explicit_summary_keeps_requested_emotion_separate(emotion, label):
    context = emotion_engine.analyze_context(summary(emotion), explicit_request=True)
    assert context["user_emotion"] == []
    assert context["requested_sticker_emotion"] == [label]


def test_direct_request_is_detected_without_explicit_flag(live_index):
    assert "生气" in returned_sticker("发一张有点生气的猫猫", live_index, explicit=False)["emotion"]


@pytest.mark.parametrize("text", ["宝宝我终于成功了", "我考试通过了", "我通过了测试"])
def test_actual_success_event_keeps_celebration(text):
    context = emotion_engine.analyze_context(text)
    assert "celebrate" in context["intent"]
    assert trigger_engine.should_send_sticker(context)


@pytest.mark.parametrize("text,expected", [
    ("实验失败了呜呜", "安慰"),
    ("宝宝我终于成功了", "庆祝"),
    ("亲亲宝宝", "亲密互动"),
])
def test_automatic_companion_scenes(live_index, text, expected):
    assert expected in returned_sticker(text, live_index, explicit=False)["scene"]


def test_personal_anger_detected_without_forcing_automatic_send():
    context = emotion_engine.analyze_context("宝宝，我今天好生气")
    assert context["user_emotion"] == ["angry"]
    assert context["requested_sticker_emotion"] == []


def test_independent_calls_and_repeated_inputs(live_index):
    for _ in range(3):
        assert "生气" in returned_sticker(summary("生气"), live_index)["emotion"]
        assert returned_sticker("给我一张点赞的猫猫", live_index)["action"] == ["点赞"]
        assert "生气" in returned_sticker(summary("有点生气"), live_index)["emotion"]
        assert "亲密互动" in returned_sticker("亲亲宝宝", live_index, explicit=False)["scene"]
        assert "生气" in returned_sticker(summary("特别生气"), live_index)["emotion"]
    assert sticker_engine.load_library.call_count == 15


def test_unknown_request_does_not_default_to_highest_priority(live_index):
    result = server.send_cat_companion(
        user_emotional_context="用户通过插件请求量子传送的猫猫表情包", explicit_request=True)
    assert "没有找到合适猫猫" in result.text
    server.fetch_image.assert_not_called()


def test_legacy_index_still_uses_caption_strength_hints(live_index):
    low = returned_sticker(summary("有点生气"), live_index)
    normal = returned_sticker(summary("生气"), live_index)
    high = returned_sticker(summary("特别生气"), live_index)
    assert "气鼓鼓" in low["tags"]
    assert any(word in normal["description"] for word in ("恼火", "火焰"))
    assert "气死了" in high["tags"]


def test_selection_diagnostics_do_not_log_full_context(live_index, caplog):
    text = summary("特别生气")
    with caplog.at_level(logging.INFO, logger="GTeacherCat"):
        returned_sticker(text, live_index)
    assert text not in caplog.text
    for field in ("context_hash=", "detected_intensity=9", "index_version=2.1",
                  "candidate_scores=", "matched_tags=", "selected_sticker_id="):
        assert field in caplog.text


def test_index_cache_refresh_observes_new_version(monkeypatch):
    first = {"version": "old", "stickers": [{"id": "old-image"}]}
    second = {"version": "new", "stickers": [{"id": "new-image"}]}
    def response(value):
        return SimpleNamespace(json=lambda: value, raise_for_status=lambda: None)
    get = Mock(side_effect=[response(first), response(second), response(first)])
    clock = Mock(side_effect=[0, 3, 6, 7, 8])
    monkeypatch.setattr(sticker_engine.requests, "get", get)
    monkeypatch.setattr(sticker_engine.time, "monotonic", clock)
    monkeypatch.setattr(sticker_engine, "_library_cache", None)
    monkeypatch.setattr(sticker_engine, "_library_loaded_at", 0)
    assert sticker_engine.load_library(ttl_seconds=5)["version"] == "old"
    assert sticker_engine.load_library(ttl_seconds=5)["version"] == "old"
    assert sticker_engine.load_library(ttl_seconds=5)["version"] == "new"
    assert sticker_engine.refresh_library()["version"] == "old"
    assert get.call_count == 3
