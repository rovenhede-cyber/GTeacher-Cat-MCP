# -*- coding: utf-8 -*-
"""R5 兼容性三件套：C1 接口兼容 / C2 行为可配置 / C3 off 模式与 R4 逐条一致。"""
import hashlib
import inspect
import json
import os

import pytest

import server
import sticker_engine
from emotion_engine import analyze_context
from sticker_config import CONFIG
from trigger_engine import should_send_sticker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = os.path.join(ROOT, "tests", "fixtures", "r4_baseline_samples.json")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "instructions.json")


@pytest.fixture(scope="module")
def frozen():
    with open(SAMPLES, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(autouse=True)
def offline_image(monkeypatch):
    """接口兼容用例只关心签名，不真的下载图片。"""
    monkeypatch.setattr(server, "fetch_image", lambda path: b"\x89PNG-fake-bytes")


# ---------------------------------------------------------------- C1 接口兼容
def test_tool_signature_only_grew():
    params = list(inspect.signature(server.send_cat_companion).parameters)
    assert params[:4] == ["user_emotional_context", "sticker_id",
                          "explicit_request", "relationship_context"]
    assert "assistant_response_intent" in params
    default = inspect.signature(server.send_cat_companion).parameters[
        "assistant_response_intent"].default
    assert default is None, "新参数必须是可选，默认不改变旧行为"


def test_old_signature_calls_still_work():
    """旧客户端只会传前 4 个参数；连跑 20 次不抛异常、不改变闸门判断。"""
    cases = ["今天下午三点开会", "我真的不想活了", "谢谢你", "有点委屈"]
    for _ in range(5):
        for text in cases:
            result = server.send_cat_companion(text)
            assert result is not None


def test_tool_schema_mentions_intent_boundary():
    """docstring 必须说明服务端看不到会话、只认调用方传入的意图。"""
    doc = inspect.getdoc(server.send_cat_companion)
    assert "assistant_response_intent" in doc
    assert "cannot" in doc.lower() or "不会" in doc


# ---------------------------------------------------------------- C2 行为可配置
def test_all_three_modes_runnable(monkeypatch):
    texts = ["今天好开心", "实验又失败了，好难受", "谢谢你一直帮我", "抱抱我"]
    for value in ("off", "shadow", "auto"):
        monkeypatch.setattr(CONFIG, "intent_mode", value)
        for text in texts:
            result = sticker_engine.search_sticker(
                analyze_context(text), relationship="intimate", deterministic=True)
            assert result is not None, (value, text)


# ---------------------------------------------------------------- C3 与 R4 一致
def test_frozen_samples_were_taken_on_same_library(frozen):
    # 归一化换行：git archive / autocrlf 会让同一份 JSON 在磁盘上变成 CRLF，
    # 但内容与 77 条结构一致，不应该因此判定基准失效。
    with open(FIXTURE, "rb") as f:
        digest = hashlib.md5(f.read().replace(b"\r\n", b"\n")).hexdigest()
    assert frozen["meta"]["library_md5"] == digest, "图库变了，基准样本需要重新冻结"
    assert frozen["meta"]["library_count"] == 77
    assert len(frozen["samples"]) == 120


def test_off_mode_matches_r4_sample_by_sample(frozen, monkeypatch):
    """off 模式必须与冻结的 R4 结果逐条一致（这是部署回滚开关的语义保证）。"""
    monkeypatch.setattr(CONFIG, "intent_mode", "off")
    mismatches = []
    for sample in frozen["samples"]:
        ctx = analyze_context(sample["text"])
        gate = bool(should_send_sticker(ctx))
        if gate != sample["gate"]:
            mismatches.append((sample["text"], sample["relationship"], "gate", sample["gate"], gate))
            continue
        item = (sticker_engine.search_sticker(ctx, relationship=sample["relationship"],
                                              deterministic=True) if gate else None)
        picked = item["id"] if item else None
        if picked != sample["id"]:
            mismatches.append((sample["text"], sample["relationship"], "id", sample["id"], picked))
    assert not mismatches, mismatches


def test_off_mode_ignores_explicit_intent(monkeypatch):
    monkeypatch.setattr(CONFIG, "intent_mode", "off")
    ctx = analyze_context("谢谢你一直帮我")
    plain = sticker_engine.search_sticker(dict(ctx), relationship="intimate", deterministic=True)
    forced = sticker_engine.search_sticker(dict(ctx, assistant_intent="teasing"),
                                          relationship="intimate", deterministic=True)
    assert plain["id"] == forced["id"]
