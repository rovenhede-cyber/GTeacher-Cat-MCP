# -*- coding: utf-8 -*-
"""本地排查工具：打印情绪分析、过滤结果与候选排名。

用法：
    python tools/explain.py "我有点难过，抱抱我"
    python tools/explain.py "爱你，媳妇～" --relationship intimate

默认离线读取 tests/fixtures/instructions.json（可用 --library 指定），
加 --remote 才从 GitHub 拉最新库。
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from emotion_engine import analyze_context          # noqa: E402
from sticker_engine import (                        # noqa: E402
    apply_filters,
    load_library,
    rank_stickers,
    set_library,
)
from trigger_engine import should_send_sticker      # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "instructions.json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("text")
    parser.add_argument("--relationship", default="unknown",
                        choices=["unknown", "intimate", "friend", "formal"])
    parser.add_argument("--library", default=None)
    parser.add_argument("--remote", action="store_true")
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()

    if args.remote:
        data = load_library(force=True)
    else:
        with open(args.library or FIXTURE, encoding="utf-8") as f:
            data = json.load(f)
        set_library(data)

    ctx = analyze_context(args.text)
    print("文本     :", args.text)
    print("情绪     :", ctx["emotion"] or "-")
    print("意图     :", ctx["intent"] or "-")
    print("动作     :", ctx["actions"] or "-")
    print("关键词   :", ctx["keywords"] or "-")
    print("强度     :", ctx["intensity"], "（规则估算，非模型打分）")
    print("危机/严肃:", ctx["crisis"], "/", ctx["serious"])
    print("关系     :", args.relationship)
    print("是否发送 :", should_send_sticker(ctx))

    kept, dropped = apply_filters(data["stickers"], ctx, relationship=args.relationship)
    print("过滤     : 保留 %d / 剔除 %d" % (len(kept), len(dropped)))
    for d in dropped[:10]:
        print("   -", d["id"], d["reason"])

    ranked = rank_stickers(ctx, items=data["stickers"], relationship=args.relationship)
    print("候选 Top%d:" % args.top)
    for row in ranked[: args.top]:
        print("   %-8s %-12s score=%-6.2f %s"
              % (row["id"], row["item"]["name"], row["score"], row["breakdown"]))


if __name__ == "__main__":
    main()
