# -*- coding: utf-8 -*-
"""R7.1 弱信号显式索图兜底。

契约（全部必须成立才兜底）：
1. 客户端显式声明 explicit_request=True
2. 原文真的有明确索图表达（防止误传 flag 的技术求助被兜底）
3. signal_count == 0（有任何可用信号时交给正常选图）
4. 无危机
5. 过滤后的池里仍有"通用安全"图

对外行为：off 与 R4 逐条一致；shadow 返回与 off 相同、只多一行预测日志；
auto 才真正兜底。选图固定顺序、可复现，不随机、不看意图。
"""
import json
import logging
import os
import subprocess
import sys

import pytest

import fallback_engine
import server
import sticker_engine
from emotion_engine import analyze_context
from sticker_config import CONFIG

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "instructions.json")
DIAGNOSE = os.path.join(ROOT, "tools", "diagnose.py")

WEAK_REQUESTS = ["发张猫猫", "给我一张猫猫", "发个猫猫表情包", "给我看看猫猫", "给我个表情包"]


@pytest.fixture()
def mode(monkeypatch):
    def _set(value):
        monkeypatch.setattr(CONFIG, "intent_mode", value)
    return _set


@pytest.fixture()
def library():
    with open(FIXTURE, encoding="utf-8") as f:
        data = json.load(f)
    sticker_engine.set_library(data)
    return data


@pytest.fixture()
def fake_image(monkeypatch):
    monkeypatch.setattr(server, "fetch_image", lambda path: b"\x89PNG-fake")


def reply_text(result):
    """send_cat_companion 返回 TextContent 或 [TextContent, ImageContent]。"""
    return result[0].text if isinstance(result, list) else result.text


def select(text, *, explicit=True, relationship="intimate"):
    trace = {}
    item = sticker_engine.search_sticker(
        analyze_context(text, explicit_request=explicit),
        relationship=relationship, trace=trace)
    return item, trace


def patched_library(edit):
    """在 fixture 的副本上改字段，避免污染仓库里的图库文件。"""
    with open(FIXTURE, encoding="utf-8") as f:
        data = json.load(f)
    for item in data["stickers"]:
        edit(item)
    sticker_engine.set_library(data)
    return data


# ---------------------------------------------------------------- 索图表达判定
@pytest.mark.parametrize("text", [
    "发张猫猫", "给我一张猫猫", "发个猫猫表情包", "给我看看猫猫",
    "来张可爱的猫猫", "麻烦发一张猫猫图", "再发个表情包", "求一张猫猫",
])
def test_request_evidence_accepts_real_requests(text):
    assert fallback_engine.request_evidence(text) is True


@pytest.mark.parametrize("text", [
    "", "   ", "这段代码报错怎么改", "帮我看看这个报错", "明天几点开会",
    "不要发猫猫", "别发表情包", "我要用猫猫做头像", "猫猫好可爱啊",
])
def test_request_evidence_rejects_non_requests(text):
    assert fallback_engine.request_evidence(text) is False


# ---------------------------------------------------------------- 主场景
@pytest.mark.parametrize("text", WEAK_REQUESTS)
def test_weak_explicit_request_returns_generic_sticker(text, mode, library):
    mode("auto")
    item, trace = select(text)
    assert item is not None, "%r 应该兜底发图" % text
    assert trace["reason"] == "generic_fallback"
    assert trace["fallback_eligible"] is True
    assert trace["fallback_reason"] == fallback_engine.REASON_WEAK_EXPLICIT
    assert trace["fallback_block_reason"] is None
    assert trace["fallback_selected_id"] == item["id"]
    assert item["id"] in fallback_engine.GENERIC_CANDIDATE_ORDER
    assert fallback_engine.generic_reject_reason(item) is None, "兜底图必须是通用安全图"


def test_fallback_selection_is_deterministic(mode, library):
    mode("auto")
    first, trace1 = select("发张猫猫")
    second, trace2 = select("给我一张猫猫")
    assert first["id"] == second["id"] == fallback_engine.GENERIC_CANDIDATE_ORDER[0]
    assert trace1["fallback_selected_id"] == trace2["fallback_selected_id"]


def test_cute_request_uses_normal_pipeline_not_fallback(mode, library):
    """“来张可爱的猫猫” 有真实请求情绪（喜欢），应走正常选图，不由兜底接管。"""
    mode("auto")
    item, trace = select("来张可爱的猫猫")
    assert item is not None
    assert trace["reason"] == "selected"
    assert "fallback_eligible" not in trace


# ---------------------------------------------------------------- 不该兜底的情况
@pytest.mark.parametrize("text", [
    "这段代码报错怎么改", "帮我看看这个报错", "怎么部署这个服务",
    "明天下午三点开会", "解释一下这个函数",
])
def test_technical_help_with_wrong_flag_does_not_fallback(text, mode, library):
    mode("auto")
    item, trace = select(text, explicit=True)
    assert item is None, "误传 explicit_request=True 不能触发兜底"
    assert trace["fallback_eligible"] is False
    assert trace["fallback_block_reason"] == fallback_engine.REASON_TEXT_MISSING
    assert trace["reason"] == "no_request_signal", "对外原因保持不变"


def test_text_request_without_client_flag_does_not_fallback(mode, library):
    """原文像索图、但客户端没声明 explicit_request：保持 R5 行为，不擅自兜底。"""
    mode("auto")
    item, trace = select("发张猫猫", explicit=False)
    assert item is None
    assert trace["fallback_block_reason"] == fallback_engine.REASON_NOT_EXPLICIT


def test_real_signals_take_priority_over_fallback(mode, library):
    mode("auto")
    item, trace = select("我好难过，发张猫猫")
    assert item is not None
    assert trace["reason"] == "selected"
    assert "fallback_eligible" not in trace
    eligible, reason = fallback_engine.evaluate(analyze_context("我好难过，发张猫猫", True))
    assert (eligible, reason) == (False, fallback_engine.REASON_SIGNALS_PRESENT)


def test_crisis_blocks_fallback_before_anything_else(mode, library):
    mode("auto")
    item, trace = select("我真的不想活了", explicit=True)
    assert item is None
    assert trace["reason"] == "gate:crisis"
    eligible, reason = fallback_engine.evaluate(
        analyze_context("我真的不想活了", explicit_request=True))
    assert (eligible, reason) == (False, fallback_engine.REASON_SAFETY)


# ---------------------------------------------------------------- 安全过滤不被绕过
def test_formal_relationship_gets_non_intimate_generic(mode, library):
    mode("auto")
    item, trace = select("发张猫猫", relationship="formal")
    assert item is not None
    assert not item.get("relationship"), "通用兜底不能选关系专属图"
    assert fallback_engine.generic_reject_reason(item) is None


def test_avoid_when_still_removes_fallback_candidates(mode, library):
    """apply_filters 剔除的图，兜底也不能捡回来。"""
    blocked = set(fallback_engine.GENERIC_CANDIDATE_ORDER[:6])

    def edit(item):
        if item["id"] in blocked:
            item["avoid_when"] = ["危机语境下不适合"]
    patched_library(edit)

    mode("auto")
    ctx = analyze_context("发张猫猫", explicit_request=True)
    ctx["strong_negative"] = True          # 触发 avoid_when 关键词
    ctx["relationship"] = "intimate"
    kept, dropped = sticker_engine.apply_filters(
        sticker_engine.load_library()["stickers"], ctx, relationship="intimate")
    assert blocked <= {d["id"] for d in dropped}, "前置条件：这 6 张应被过滤掉"

    trace = {}
    selected = sticker_engine.choose_with_fallback(ctx, kept, mode="auto", trace=trace)
    assert selected is not None
    assert selected["id"] not in blocked
    assert selected["id"] == fallback_engine.GENERIC_CANDIDATE_ORDER[6]


def test_no_safe_candidate_reports_reason_instead_of_forcing(mode, library):
    """池里没有合格通用图时：不发图，并给出明确原因。"""
    def edit(item):
        if item["id"] in fallback_engine.GENERIC_CANDIDATE_ORDER:
            item["emotion"] = ["生气"]        # 变成负向情绪 -> 不再通用
    patched_library(edit)

    mode("auto")
    item, trace = select("发张猫猫")
    assert item is None
    assert trace["fallback_eligible"] is True
    assert trace["fallback_block_reason"] == "no_generic_candidate"
    assert trace["reason"] == "no_generic_candidate"


# ---------------------------------------------------------------- 三模式
def test_off_mode_keeps_r4_behaviour(mode, library, caplog):
    mode("off")
    with caplog.at_level(logging.INFO, logger="GTeacherCat"):
        item, trace = select("发张猫猫")
    assert item is None
    assert trace == {"reason": "no_request_signal"}, "off 必须与 R4 完全一致"
    assert "r71_fallback" not in caplog.text
    assert "r71_shadow" not in caplog.text


def test_shadow_returns_same_as_off_and_logs_prediction(mode, library, caplog):
    mode("off")
    with caplog.at_level(logging.INFO, logger="GTeacherCat"):
        off_item, _ = select("发张猫猫")
    mode("shadow")
    with caplog.at_level(logging.INFO, logger="GTeacherCat"):
        shadow_item, trace = select("发张猫猫")

    assert off_item is None and shadow_item is None, "shadow 不得改变对外返回"
    assert trace["fallback_eligible"] is True, "shadow 仍需算出预测"
    assert "r71_shadow" in caplog.text
    assert "r71_would_select=%s" % fallback_engine.GENERIC_CANDIDATE_ORDER[0] in caplog.text
    assert "r71_fallback " not in caplog.text, "shadow 不得真的兜底"
    assert "发张" not in caplog.text, "日志不得记录原文"


def test_auto_only_fires_when_all_conditions_hold(mode, library):
    mode("auto")
    fired = select("发张猫猫")[1]
    not_fired = select("发张猫猫", explicit=False)[1]
    assert fired["fallback_eligible"] is True
    assert not_fired["fallback_eligible"] is False


# ---------------------------------------------------------------- 服务端行为
def test_server_returns_image_for_weak_request_in_auto(mode, library, fake_image):
    mode("auto")
    result = server.send_cat_companion("发张猫猫", explicit_request=True)
    assert isinstance(result, list) and len(result) == 2
    assert result[1].type == "image"
    assert "猫猫名称：" in result[0].text
    assert "没有找到合适猫猫" not in result[0].text


def test_server_text_is_identical_in_shadow_and_off(mode, library, fake_image):
    mode("shadow")
    shadow = server.send_cat_companion("发张猫猫", explicit_request=True)
    mode("off")
    off = server.send_cat_companion("发张猫猫", explicit_request=True)
    assert reply_text(shadow) == reply_text(off)
    assert "没有找到合适猫猫" in reply_text(shadow)


def test_blank_context_with_explicit_request_sends_nothing(mode, library, fake_image):
    mode("auto")
    result = server.send_cat_companion("", explicit_request=True)
    assert not isinstance(result, list)
    assert "没有收到用户原话" in reply_text(result)


def test_crisis_with_explicit_request_sends_nothing(mode, library, fake_image):
    mode("auto")
    result = server.send_cat_companion("我真的不想活了", explicit_request=True)
    assert not isinstance(result, list)
    assert "当前场景不需要发送猫猫" in reply_text(result)


def test_no_candidate_message_is_explicit_about_library_gap(mode, library, fake_image):
    def edit(item):
        if item["id"] in fallback_engine.GENERIC_CANDIDATE_ORDER:
            item["emotion"] = ["生气"]
    patched_library(edit)
    mode("auto")
    result = server.send_cat_companion("发张猫猫", explicit_request=True)
    assert not isinstance(result, list)
    assert "没有找到合适猫猫" in reply_text(result)
    assert "没有适合直接发送的通用图片" in reply_text(result)


# ---------------------------------------------------------------- 候选表可维护性
def test_curated_candidates_exist_and_are_safe(library):
    index = {item["id"]: item for item in library["stickers"]}
    for sticker_id in fallback_engine.GENERIC_CANDIDATE_ORDER:
        assert sticker_id in index, "候选表引用了图库里不存在的 id：%s" % sticker_id
        assert fallback_engine.generic_reject_reason(index[sticker_id]) is None, sticker_id


def test_every_generic_candidate_is_reachable(library):
    """候选表里的每一张都应能在池子里被选中（顺序生效，不是死数据）。"""
    pool = list(library["stickers"])
    for expected in fallback_engine.GENERIC_CANDIDATE_ORDER:
        item, _ = fallback_engine.select_generic(
            pool, order=(expected,))
        assert item is not None and item["id"] == expected


# ---------------------------------------------------------------- 诊断脚本（CP936）
def test_diagnose_reports_fallback_under_legacy_encoding():
    """不设 PYTHONUTF8、stdout 按 GBK 输出时，--json 仍是合法 UTF-8 且带兜底字段。"""
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in {"PYTHONUTF8", "PYTHONLEGACYWINDOWSSTDIO"}}
    env["PYTHONIOENCODING"] = "gbk"
    proc = subprocess.run(
        [sys.executable, DIAGNOSE, "发张猫猫", "--explicit", "--mode", "auto",
         "--json", "--library", FIXTURE],
        cwd=ROOT, env=env, capture_output=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")[-500:]
    data = json.loads(proc.stdout.decode("utf-8"))
    assert data["fallback"]["eligible"] is True
    assert data["fallback"]["selected_id"] == fallback_engine.GENERIC_CANDIDATE_ORDER[0]
    assert data["selection"]["sticker"]["id"] == fallback_engine.GENERIC_CANDIDATE_ORDER[0]
