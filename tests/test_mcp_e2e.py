# -*- coding: utf-8 -*-
"""真实 MCP 端到端测试：uvicorn 子进程 + Streamable HTTP 客户端。

不依赖外网：图库与图片由临时目录里的本地 HTTP 站点提供。
不触碰 8000 / 8001 / 8010：端口随机分配。

覆盖：初始化、tools/list schema、明确索图返图、无候选、空上下文、
危机拦截、三模式差异、未知 sticker_id。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

from mcp_harness import CatServer, call  # noqa: E402

_SERVERS = {}


@pytest.fixture(scope="session", autouse=True)
def _teardown_servers():
    """会话结束时关闭所有子进程与静态站点（hook 定义在测试模块里不会生效，所以用夹具）。"""
    yield
    while _SERVERS:
        _, srv = _SERVERS.popitem()
        srv.__exit__()


def server(mode):
    """按模式复用同一个子进程（启动一次约 2s，避免每个用例都起服务）。"""
    if mode not in _SERVERS:
        srv = CatServer(mode=mode).__enter__()
        _SERVERS[mode] = srv
    return _SERVERS[mode]


def send(mode, **kwargs):
    return call(server(mode).url, kwargs)


# ------------------------------------------------------------------ 初始化与工具发现
def test_initialize_and_tool_schema():
    result = send("shadow", user_emotional_context="抱抱我")
    assert result["server"] == "GTeacher Cat"
    assert result["is_error"] is False
    assert result["schema"] == [
        "assistant_response_intent", "explicit_request",
        "relationship_context", "sticker_id", "user_emotional_context",
    ]


# ------------------------------------------------------------------ 报喜 / 明确索图（问题 A、B）
def test_auto_celebrate_returns_image():
    result = send("shadow",
                  user_emotional_context="哥哥！我拿到 offer 啦！！！",
                  assistant_response_intent="celebrate",
                  relationship_context="intimate")
    assert result["is_error"] is False
    assert result["images"] == ["image/png"]
    assert "猫猫名称：" in result["text"]


@pytest.mark.parametrize("intent", [None, "celebrate"])
def test_explicit_request_returns_image(intent):
    """问题 B：明确索图必须出图；带不带 assistant_response_intent 都不该变成“没有候选”。"""
    payload = dict(user_emotional_context="哥哥，我今天特别开心！给我发一张猫猫表情包！",
                   explicit_request=True)
    if intent:
        payload["assistant_response_intent"] = intent
    result = send("shadow", **payload)
    assert result["images"] == ["image/png"], result["text"]
    assert "没有找到合适猫猫" not in result["text"]


def test_explicit_request_with_celebrate_words_returns_image():
    result = send("shadow",
                  user_emotional_context="哥哥！我拿到 offer 啦！快发一张庆祝猫猫！",
                  assistant_response_intent="celebrate",
                  relationship_context="intimate", explicit_request=True)
    assert result["images"] == ["image/png"], result["text"]


# ------------------------------------------------------------------ 输入缺失要说清楚
def test_blank_context_is_reported_as_missing_input():
    """空上下文不能被说成“场景不需要发图”，否则会被误判为闸门缺陷。"""
    result = send("shadow", assistant_response_intent="celebrate")
    assert result["is_error"] is False
    assert result["images"] == []
    assert "没有收到用户原话" in result["text"]
    assert "当前场景不需要发送猫猫" not in result["text"]


def test_explicit_request_without_any_signal_explains_reason():
    result = send("shadow", user_emotional_context="发张猫猫", explicit_request=True)
    assert result["images"] == []
    assert "没有找到合适猫猫" in result["text"]
    assert "没识别到具体情绪或画面要求" in result["text"]


# ------------------------------------------------------------------ 安全
def test_crisis_is_blocked_even_with_explicit_request():
    result = send("auto", user_emotional_context="我真的不想活了", explicit_request=True)
    assert result["images"] == []
    assert "当前场景不需要发送猫猫" in result["text"]


def test_unknown_sticker_id_reports_not_found():
    result = send("shadow", user_emotional_context="发张猫猫", sticker_id="cat-999")
    assert result["images"] == []
    assert "未找到指定表情包 ID" in result["text"]


def test_relationship_filters_affection_sticker_for_formal():
    """亲昵专属图在 formal 关系下不能被 sticker_id 强行发出（I4）。"""
    result = send("shadow", user_emotional_context="发张猫猫",
                  sticker_id="cat-042", relationship_context="formal")
    assert result["images"] == []
    assert "没有找到合适猫猫" in result["text"]


# ------------------------------------------------------------------ 三模式
@pytest.mark.parametrize("text,explicit", [
    ("哈哈你怎么又迟到了，狗头", False),
])
def test_off_and_auto_differ_on_teasing(text, explicit):
    off = send("off", user_emotional_context=text, explicit_request=explicit)
    auto = send("auto", user_emotional_context=text, explicit_request=explicit)
    assert off["images"] and auto["images"]
    assert off["text"] != auto["text"], "auto 与 off 对打趣场景应有不同选择"


def test_apology_returns_none_in_auto():
    """图库里没有道歉图：返回 None，且说明原因，不拿感谢/贴贴图顶替。

    注意语料选择：纯道歉句（“抱歉，是我搞错了”）没有情绪信号，闸门会直接拦住，
    根本走不到道歉分支——这是闸门先于意图的既定设计。要验证道歉分支，
    用户话里必须本身带情绪（“抱歉让你难受了”）。
    """
    result = send("auto", user_emotional_context="抱歉让你难受了",
                  assistant_response_intent="apology")
    assert result["images"] == []
    assert "没有找到合适猫猫" in result["text"]
    assert "道歉图" in result["text"]


def test_pure_apology_is_blocked_by_gate_not_by_intent():
    """意图不得绕过闸门：纯道歉句没有情绪信号，闸门拦住。"""
    result = send("auto", user_emotional_context="抱歉，是我搞错了",
                  assistant_response_intent="apology")
    assert result["images"] == []
    assert "当前场景不需要发送猫猫" in result["text"]


def test_shadow_returns_same_as_off():
    payload = dict(user_emotional_context="哥哥！我拿到 offer 啦！快发一张庆祝猫猫！",
                   explicit_request=True, assistant_response_intent="celebrate")
    shadow = send("shadow", **payload)
    off = send("off", **payload)
    # 两个服务进程的静态端口不同，图片地址前缀会不同，只比图名这一行
    assert shadow["text"].splitlines()[0] == off["text"].splitlines()[0], \
        "shadow 不得改变对外返回"


def test_shadow_logs_prediction_without_raw_text():
    srv = server("shadow")
    send("shadow", user_emotional_context="哥哥！我拿到 offer 啦！！！",
         assistant_response_intent="celebrate")
    log = srv.log_text()
    assert "r5_shadow" in log
    assert "r5_shadow_id=" in log
    assert "哥哥" not in log and "offer" not in log, "日志不得记录原始对话"
    assert "r5_input input_len=" in log, "缺少输入侧诊断日志"


# ------------------------------------------------------------------ R7.1 弱信号兜底
def test_weak_explicit_request_returns_image_in_auto():
    """auto：无信号的明确索图（“发张猫猫”）要拿到通用安全图，而不是“没有找到”。"""
    result = send("auto", user_emotional_context="发张猫猫", explicit_request=True)
    assert result["is_error"] is False
    assert result["images"] == ["image/png"], result["text"]
    assert "猫猫名称：" in result["text"]
    assert "没有找到合适猫猫" not in result["text"]


def test_weak_explicit_request_stays_none_in_shadow_and_off():
    """shadow / off 对外结果必须一致（都还是 R4 行为）。"""
    shadow = send("shadow", user_emotional_context="发张猫猫", explicit_request=True)
    off = send("off", user_emotional_context="发张猫猫", explicit_request=True)
    assert shadow["images"] == off["images"] == []
    assert shadow["text"].splitlines()[0] == off["text"].splitlines()[0]
    assert "没有找到合适猫猫" in off["text"]


def test_wrong_flag_does_not_trigger_fallback_in_auto():
    """误传 explicit_request=True 的技术求助不得兜底发图。"""
    result = send("auto", user_emotional_context="这段代码报错怎么改",
                  explicit_request=True)
    assert result["images"] == []
    assert "没有找到合适猫猫" in result["text"]


def test_shadow_logs_fallback_prediction():
    srv = server("shadow")
    send("shadow", user_emotional_context="发张猫猫", explicit_request=True)
    log = srv.log_text()
    assert "r71_shadow" in log, "shadow 要记录“如果开 auto 会发哪张”"
    assert "r71_would_select=cat-" in log
    assert "发张" not in log, "日志不得记录原始对话"
