# -*- coding: utf-8 -*-
"""诊断能力测试：闸门原因、输入信号量、选图原因回传、空输入防线。

这些是 R5 联调教训的固化：出问题时必须能从日志/返回里分清
“闸门拦住 / 输入没信号 / 图库没有这张 / 正常选中”。
"""
import io
import json
import os
import subprocess
import sys

import pytest

import server
import sticker_engine
import tools.diagnose as diagnose
from emotion_engine import analyze_context
from trigger_engine import gate_reason, should_send_sticker


@pytest.fixture()
def library():
    with open("tests/fixtures/instructions.json", encoding="utf-8") as f:
        data = json.load(f)
    sticker_engine.set_library(data)
    return data


@pytest.fixture()
def fake_image(monkeypatch):
    monkeypatch.setattr(server, "fetch_image", lambda path: b"\x89PNG-fake")


# ------------------------------------------------------------------ 闸门原因
@pytest.mark.parametrize("ctx,expected", [
    ({"crisis": True}, "crisis"),
    ({"explicit_sticker_request": True}, "explicit_request"),
    ({"serious": True}, "serious_task"),
    ({"scenes": ["庆祝"]}, "scene"),
    ({"emotion": ["开心"]}, "signal"),
    ({}, "no_signal"),
    ({"intent": ["help"]}, "help_only"),
])
def test_gate_reason_matches_decision(ctx, expected):
    triggered, reason = gate_reason(ctx)
    assert reason == expected
    assert triggered is should_send_sticker(ctx), "gate_reason 与 should_send_sticker 必须完全一致"


def test_gate_reason_does_not_change_behaviour(library):
    """原因只是标签：对同一批语料，triggered 必须与旧布尔接口一致。"""
    for text in ["抱抱我", "今天下午三点开会", "我真的不想活了", "这段代码报错怎么改"]:
        ctx = analyze_context(text)
        assert gate_reason(ctx)[0] == should_send_sticker(ctx)


# ------------------------------------------------------------------ 输入信号量
def test_signal_count_is_zero_for_blank_or_signal_free_text():
    assert analyze_context("")["signal_count"] == 0
    assert analyze_context("   ")["signal_count"] == 0
    assert analyze_context("嗯")["signal_count"] == 0


def test_signal_count_is_positive_for_emotional_text():
    assert analyze_context("我好难过")["signal_count"] >= 1
    assert analyze_context("哥哥！我拿到 offer 啦！！！")["signal_count"] >= 1


# ------------------------------------------------------------------ 空输入防线
def test_blank_context_returns_missing_input_message(library, fake_image, caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="GTeacherCat"):
        result = server.send_cat_companion("   ")
    text = result[0].text if isinstance(result, list) else result.text
    assert "没有收到用户原话" in text
    assert "当前场景不需要发送猫猫" not in text
    assert "r5_input_empty" in caplog.text


def test_blank_context_still_allows_exact_sticker_id(library, fake_image):
    """旧接口兼容：显式指定 sticker_id 时，即使没有情感上下文也要能发。"""
    result = server.send_cat_companion("", sticker_id="cat-009")
    assert isinstance(result, list)
    assert "cat-009" in result[0].text or "猫猫名称" in result[0].text


# ------------------------------------------------------------------ 选图原因回传
def test_trace_reports_gate_block(library):
    trace = {}
    result = sticker_engine.search_sticker(
        analyze_context("今天下午三点开会"), relationship="intimate", trace=trace)
    assert result is None
    assert trace["reason"] == "gate:no_signal"


def test_trace_reports_no_request_signal(library):
    trace = {}
    result = sticker_engine.search_sticker(
        analyze_context("发张猫猫", explicit_request=True), relationship="intimate", trace=trace)
    assert result is None
    assert trace["reason"] == "no_request_signal"


def test_trace_reports_selected(library):
    trace = {}
    result = sticker_engine.search_sticker(
        analyze_context("抱抱我"), relationship="intimate", trace=trace)
    assert result is not None
    assert trace["reason"] == "selected"


def test_none_result_message_carries_reason(library, fake_image):
    result = server.send_cat_companion("发张猫猫", explicit_request=True)
    text = result[0].text if isinstance(result, list) else result.text
    assert "没有找到合适猫猫" in text, "旧前缀必须保留"
    assert "没识别到具体情绪或画面要求" in text


# ------------------------------------------------------- 诊断工具可执行 & 输出编码
# Windows 默认代码页是 CP936：stdout 被重定向时子进程按 locale 写字节，调用方按
# UTF-8 读就会 UnicodeDecodeError（subprocess 里表现为 stdout=None）。下面所有
# 子进程用例都显式清掉 PYTHONUTF8 / PYTHONIOENCODING，保证不依赖“事先开 UTF-8 模式”。
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIAGNOSE = os.path.join(ROOT, "tools", "diagnose.py")
FIXTURE_PATH = os.path.join(ROOT, "tests", "fixtures", "instructions.json")


def _legacy_env(**extra):
    """还原“用户没设任何 UTF-8 环境变量”的默认场景。"""
    env = {
        k: v for k, v in os.environ.items()
        if k.upper() not in {"PYTHONUTF8", "PYTHONIOENCODING", "PYTHONLEGACYWINDOWSSTDIO"}
    }
    env.update(extra)
    return env


def _run_diagnose(*argv, env_extra=None):
    """按字节采集后严格按 UTF-8 解码。

    不用 text=True：编码不一致时 subprocess 会在读线程里吞掉异常、把 stdout 变成
    None，掩盖真实原因。这里自己解码，出错就带原始字节前缀报出来。
    """
    proc = subprocess.run(
        [sys.executable, DIAGNOSE, *argv],
        cwd=ROOT, env=_legacy_env(**(env_extra or {})),
        capture_output=True, timeout=180,
    )
    try:
        proc.out = proc.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AssertionError(
            "tools/diagnose.py 的 stdout 不是 UTF-8（仍按 locale 编码写出）：%s / 前 60 字节=%r"
            % (exc, proc.stdout[:60])) from None
    proc.err = proc.stderr.decode("utf-8", "replace")
    return proc


def test_diagnose_tool_runs_and_reports_pipeline():
    """未设置 PYTHONUTF8 的默认环境也要跑通，且 --json 能被 UTF-8 消费方解析。"""
    out = _run_diagnose("抱抱我", "--json", "--library", FIXTURE_PATH)
    assert out.returncode == 0, out.err[-800:]
    data = json.loads(out.out)
    assert data["library"]["count"] == 77
    assert data["gate"]["triggered"] is True
    assert data["selection"]["sticker"] is not None
    assert data["filters"]["kept"] <= 77
    # 中文必须原样往返，不能被替换成 ?
    assert data["input"]["text"] == "抱抱我"


@pytest.mark.parametrize("forced", [
    {},                               # 默认：Windows 上是 cp936，Linux 上是 UTF-8
    {"PYTHONIOENCODING": "gbk"},      # 显式模拟 CP936 启动，任何平台都可复现
])
def test_diagnose_json_is_utf8_regardless_of_stdio_locale(forced):
    """输出边界固定 UTF-8：与解释器启动时的编码、平台都无关。"""
    out = _run_diagnose("抱抱我", "--json", "--library", FIXTURE_PATH, env_extra=forced)
    assert out.returncode == 0, out.err[-800:]
    data = json.loads(out.out)
    assert data["input"]["text"] == "抱抱我"
    assert data["selection"]["sticker"]["name"], "选中结果要带上中文图名"


def test_diagnose_human_output_is_utf8_too():
    out = _run_diagnose("抱抱我", "--library", FIXTURE_PATH)
    assert out.returncode == 0, out.err[-800:]
    assert "模式" in out.out and "选择" in out.out


def test_diagnose_json_is_pure_json_without_log_noise():
    """--json 的 stdout 只能是一个 JSON 文档；提示/告警必须走 stderr。"""
    out = _run_diagnose("抱抱我", "--json", "--intent", "不是意图",
                        "--library", FIXTURE_PATH)
    assert out.returncode == 0, out.err[-800:]
    text = out.out.strip()
    assert text.startswith("{") and text.endswith("}"), text[:200]
    json.loads(text)                                   # 整体可解析 => 没混入其他文本
    for noise in (" - INFO - ", " - WARNING - ", " - ERROR - ", "Traceback"):
        assert noise not in text, "日志混进了 --json 的 stdout"
    assert "未知意图" in out.err, "告警应走 stderr"


def test_force_utf8_stdio_reconfigures_both_streams(monkeypatch):
    calls = []

    class FakeStream:
        def reconfigure(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(sys, "stdout", FakeStream())
    monkeypatch.setattr(sys, "stderr", FakeStream())
    diagnose.force_utf8_stdio()
    assert len(calls) == 2
    assert all(c["encoding"] == diagnose.OUTPUT_ENCODING == "utf-8" for c in calls)


def test_force_utf8_stdio_tolerates_streams_without_reconfigure():
    """被替换成 StringIO / pytest 捕获流时不能抛异常。"""
    streams = [io.StringIO(), object()]
    diagnose.force_utf8_stdio(streams)          # 不抛即通过
    streams[0].write("中文")
    assert streams[0].getvalue() == "中文"


def test_force_utf8_stdio_leaves_console_streams_alone(monkeypatch):
    """直连终端不改编码（现代 CPython 控制台已是 UTF-8），只管重定向场景。"""
    calls = []

    class FakeTty:
        def isatty(self):
            return True

        def reconfigure(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(sys, "stdout", FakeTty())
    monkeypatch.setattr(sys, "stderr", FakeTty())
    diagnose.force_utf8_stdio()
    assert calls == []


def test_emit_json_writes_utf8_bytes_only(monkeypatch):
    class FakeStdout:
        def __init__(self):
            self.buffer = io.BytesIO()
            self.flushed = 0

        def flush(self):
            self.flushed += 1

    fake = FakeStdout()
    monkeypatch.setattr(sys, "stdout", fake)
    diagnose.emit_json({"text": "抱抱我", "n": 1})
    raw = fake.buffer.getvalue()
    assert raw.decode("utf-8") == '{\n  "text": "抱抱我",\n  "n": 1\n}\n'
    assert json.loads(raw.decode("utf-8"))["text"] == "抱抱我"
