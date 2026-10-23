# -*- coding: utf-8 -*-
"""R5 本地 MCP 联调脚本（隔离端口、完全离线图库，不碰 8000/8001/8010）。

用法：
    python tools/mcp_smoke.py                    # 默认 shadow
    python tools/mcp_smoke.py --mode auto
    python tools/mcp_smoke.py --mode off --json

它做的是真实 HTTP 联调：起一个本地图库站点 + 一个 MCP 服务子进程，
然后用 mcp SDK 的 Streamable HTTP 客户端 initialize -> tools/list -> tools/call。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp_harness import CatServer, call  # noqa: E402

CASES = [
    ("A 报喜（自动）", {
        "user_emotional_context": "哥哥！我拿到 offer 啦！！！",
        "assistant_response_intent": "celebrate",
        "relationship_context": "intimate"}),
    ("B 报喜+明确索图", {
        "user_emotional_context": "哥哥！我拿到 offer 啦！快发一张庆祝猫猫！",
        "assistant_response_intent": "celebrate",
        "relationship_context": "intimate", "explicit_request": True}),
    ("C 明确索图-无意图", {
        "user_emotional_context": "哥哥，我今天特别开心！给我发一张猫猫表情包！",
        "explicit_request": True}),
    ("D 明确索图-有意图", {
        "user_emotional_context": "哥哥，我今天特别开心！给我发一张猫猫表情包！",
        "explicit_request": True, "assistant_response_intent": "celebrate"}),
    ("E 空上下文", {"assistant_response_intent": "celebrate"}),
    ("F 纯索图无信号", {
        "user_emotional_context": "发张猫猫", "explicit_request": True}),
    ("G 危机场景", {
        "user_emotional_context": "我真的不想活了", "explicit_request": True}),
    ("H 技术求助", {
        "user_emotional_context": "这段 Python 报错怎么改？", "explicit_request": True}),
    ("I 弱信号-正式关系", {
        "user_emotional_context": "发张猫猫", "explicit_request": True,
        "relationship_context": "formal"}),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="shadow", choices=["off", "shadow", "auto"],
                        help="自建测试服务使用的模式（--url 模式下仅用于标注）")
    parser.add_argument("--url", default=None,
                        help="直连已在运行的服务，例如 http://127.0.0.1:8010/mcp（只读调用，不重启它）")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    rows = []

    def run_cases(url):
        for label, payload in CASES:
            try:
                res = call(url, payload)
            except Exception as exc:  # noqa: BLE001 联调脚本要如实报错
                res = {"error": "%s: %s" % (type(exc).__name__, exc)}
            rows.append({"case": label, "args": payload, "result": res})

    if args.url:
        run_cases(args.url)
        log = ""
        label_mode = "external:" + args.url
    else:
        with CatServer(mode=args.mode) as srv:
            run_cases(srv.url)
            log = srv.log_text()
        label_mode = args.mode

    if args.json:
        print(json.dumps({"mode": label_mode, "rows": rows}, ensure_ascii=False, indent=2))
        return

    print("模式: %s" % label_mode)
    for row in rows:
        res = row["result"]
        if "error" in res:
            print("  %-16s ERROR %s" % (row["case"], res["error"]))
            continue
        print("  %-16s server=%s is_error=%s images=%s schema=%s" % (
            row["case"], res["server"], res["is_error"], res["images"], res["schema"]))
        print("      %s" % res["text"].replace("\n", " | ")[:120])

    interesting = [l for l in log.splitlines()
                   if "r5_outcome" in l or "r5_input" in l or "gate_reason" in l
                   or "r71_fallback" in l or "r71_shadow" in l]
    if interesting:
        print("--- 服务端诊断日志（尾 8 条）---")
        for line in interesting[-8:]:
            print("   ", line[:170])


if __name__ == "__main__":
    main()
