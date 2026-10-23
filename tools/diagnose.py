# -*- coding: utf-8 -*-
"""全链路诊断：一条命令看清“为什么不发图 / 为什么选了这张”。

用法：
    python tools/diagnose.py "哥哥！我拿到 offer 啦！！！"
    python tools/diagnose.py "发张猫猫" --explicit --intent celebrate --mode auto
    python tools/diagnose.py "抱抱我" --relationship formal --json
    python tools/diagnose.py "抱抱我" --remote          # 走远程图库（默认读仓库 fixture）

输出包含：模式、图库版本/条数、三层语义、闸门结果与原因、过滤前后数量与原因分布、
候选打分、最终选择与图片行为标注、以及“没选出来”的确切原因。
不打印文本原文以外的东西，也不读取任何环境变量值。
"""
import argparse
import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import intent_engine                                   # noqa: E402
import sticker_config                                  # noqa: E402
import sticker_engine                                  # noqa: E402
from emotion_engine import analyze_context             # noqa: E402
from trigger_engine import gate_reason                 # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "instructions.json")

# 输出编码契约：本工具的一切输出（含 --json）都是 UTF-8。
OUTPUT_ENCODING = "utf-8"


def force_utf8_stdio(streams=None):
    """把 stdout/stderr 固定成 UTF-8，不受 Windows 默认代码页（CP936）影响。

    Windows 下 stdout 被重定向到管道/文件时，Python 用 locale 编码（cp936）写字节，
    JSON 里只要有一个中文就变成非 UTF-8 字节流：调用方按 UTF-8 解码会
    UnicodeDecodeError（subprocess 里表现为 stdout=None）。这里只在输出边界把本进程的
    两个标准流改成 UTF-8——不改系统代码页，也不要求用户先设 PYTHONUTF8=1。
    流被替换成没有编码概念的文本缓冲（测试内直调 main）时自动跳过。
    """
    for stream in (sys.stdout, sys.stderr) if streams is None else streams:
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        # 直连终端时交给平台：现代 CPython 的控制台流本来就是 UTF-8，
        # 保留判断可避免在 PYTHONLEGACYWINDOWSSTDIO 等旧模式下把编码改坏。
        if getattr(stream, "isatty", None) and stream.isatty():
            continue
        try:
            reconfigure(encoding=OUTPUT_ENCODING, errors="replace")
        except (ValueError, OSError):      # 已 detach 的流：保持原样，不阻断诊断
            pass


def emit_json(report):
    """--json 只输出一个 JSON 文档，不混日志/提示；字节层直接写 UTF-8。"""
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:                     # 被替换成 StringIO：按文本写
        sys.stdout.write(payload + "\n")
        return
    try:
        sys.stdout.flush()
    except (ValueError, OSError):
        pass
    buffer.write(payload.encode(OUTPUT_ENCODING) + b"\n")
    buffer.flush()


def load(args):
    if args.remote:
        return sticker_engine.load_library(force_refresh=True), "remote"
    path = args.library or FIXTURE
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    sticker_engine.set_library(data)
    return sticker_engine.load_library(), "local:" + os.path.relpath(path, ROOT)


def main():
    # 必须早于任何输出（包括 argparse 的用法/错误信息）
    force_utf8_stdio()
    parser = argparse.ArgumentParser()
    parser.add_argument("text")
    parser.add_argument("--mode", default=None, choices=["off", "shadow", "auto"])
    parser.add_argument("--intent", default=None)
    parser.add_argument("--explicit", action="store_true")
    parser.add_argument("--relationship", default="intimate",
                        choices=["intimate", "friend", "formal", "unknown"])
    parser.add_argument("--library", default=None)
    parser.add_argument("--remote", action="store_true")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.mode:
        setattr(sticker_config.CONFIG, "intent_mode", args.mode)
    mode = sticker_engine.intent_mode()

    data, source = load(args)

    ctx = analyze_context(args.text, explicit_request=bool(args.explicit))
    ctx["relationship"] = sticker_engine.resolve_relationship(args.relationship)
    if mode != "off" and args.intent:
        normalized = intent_engine.normalize_intent(args.intent)
        if normalized:
            ctx["assistant_intent"] = normalized
            ctx["intent_source"] = "explicit"
        else:
            print("⚠️  未知意图 %r，将回落为推导" % args.intent, file=sys.stderr)

    triggered, reason = gate_reason(ctx)
    kept, dropped = sticker_engine.apply_filters(
        data["stickers"], ctx, relationship=ctx["relationship"])

    ctx["_intent_active"] = mode == "auto"
    trace = {}
    selected = sticker_engine.choose_with_fallback(
        ctx, kept, mode=mode, deterministic=True, trace=trace)

    ranked = sticker_engine._rank(ctx, kept)
    # 零用户信号时选择会被提前拦下，此时列出“意图分撑起来的候选”只会误导排查
    show_candidates = trace.get("reason") not in {"no_request_signal", "gate:no_signal"}
    report = {
        "mode": mode,
        "library": {"version": data.get("version"), "count": len(data["stickers"]),
                    "source": source},
        "input": {"text": args.text, "length": len(args.text),
                  "signal_count": ctx.get("signal_count"),
                  "context_hash": ctx.get("context_hash")},
        "analysis": {
            "user_emotion": ctx.get("user_emotion"),
            "requested_emotion": ctx.get("requested_sticker_emotion"),
            "requested_visual_features": ctx.get("requested_visual_features"),
            "intent": ctx.get("intent"),
            "actions": ctx.get("actions"),
            "scenes": ctx.get("scenes"),
            "keywords": ctx.get("keywords"),
            "intensity": ctx.get("intensity"),
            "crisis": ctx.get("crisis"),
            "serious": ctx.get("serious"),
            "explicit_request": ctx.get("explicit_sticker_request"),
            "assistant_intent": ctx.get("assistant_intent"),
            "intent_source": ctx.get("intent_source"),
        },
        "gate": {"triggered": triggered, "reason": reason},
        "filters": {
            "kept": len(kept),
            "dropped": len(dropped),
            "reasons": dict(collections.Counter(
                d["reason"].split(":")[0] for d in dropped)),
            "dropped_ids": [d["id"] for d in dropped][:10],
        },
        "candidates": [
            {"id": r["id"], "name": r["item"].get("name"), "score": round(r["score"], 2),
             "breakdown": r["breakdown"]}
            for r in (ranked[: args.top] if show_candidates else [])
        ],
        "selection": {
            "reason": trace.get("reason"),
            "sticker": None if selected is None else {
                "id": selected.get("id"),
                "name": selected.get("name"),
                "description": selected.get("description"),
                "file": selected.get("file"),
                "behaviors": intent_engine.behaviors_for(selected)["behaviors"],
                "behavior_source": intent_engine.behaviors_for(selected)["source"],
            },
        },
        # R7.1：弱信号显式索图兜底（off 模式不评估，这两项为 None）
        "fallback": {
            "eligible": trace.get("fallback_eligible"),
            "reason": trace.get("fallback_reason"),
            "block_reason": trace.get("fallback_block_reason"),
            "selected_id": trace.get("fallback_selected_id"),
        },
    }

    if args.json:
        emit_json(report)
        return

    lib = report["library"]
    print("模式      : %s" % report["mode"])
    print("图库      : v%s / %d 条 / %s" % (lib["version"], lib["count"], lib["source"]))
    print("输入      : len=%d signal_count=%s hash=%s" % (
        report["input"]["length"], report["input"]["signal_count"],
        report["input"]["context_hash"]))
    a = report["analysis"]
    print("用户情绪  : %s" % (a["user_emotion"] or "-"))
    print("请求情绪  : %s  画面=%s" % (a["requested_emotion"] or "-",
                                       a["requested_visual_features"] or "-"))
    print("动作/场景 : %s / %s" % (a["actions"] or "-", a["scenes"] or "-"))
    print("强度/危机 : %s / %s   严肃=%s  明确索图=%s" % (
        a["intensity"], a["crisis"], a["serious"], a["explicit_request"]))
    print("助手意图  : %s（%s）" % (a["assistant_intent"] or "-", a["intent_source"]))
    print("闸门      : %s  原因=%s" % (report["gate"]["triggered"], report["gate"]["reason"]))
    f = report["filters"]
    print("过滤      : 保留 %d / 剔除 %d  原因分布=%s" % (f["kept"], f["dropped"], f["reasons"]))
    print("候选 Top%d :" % args.top)
    for row in report["candidates"]:
        print("   %-8s %-14s score=%-6.2f %s" % (
            row["id"], row["name"], row["score"], row["breakdown"]))
    sel = report["selection"]
    if sel["sticker"] is None:
        print("选择      : None  原因=%s" % sel["reason"])
    else:
        s = sel["sticker"]
        print("选择      : %s %s  行为=%s(%s)" % (
            s["id"], s["name"], s["behaviors"], s["behavior_source"]))
    fb = report["fallback"]
    if fb["eligible"] is not None:
        # shadow 下这张图不会真的发出，标注成“预测”，避免误读
        label = "预测" if report["mode"] == "shadow" else "命中"
        print("兜底      : eligible=%s 原因=%s 拒绝原因=%s %s=%s" % (
            fb["eligible"], fb["reason"] or "-", fb["block_reason"] or "-",
            label, fb["selected_id"] or "-"))


if __name__ == "__main__":
    main()
