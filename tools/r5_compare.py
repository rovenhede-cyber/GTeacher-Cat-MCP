# -*- coding: utf-8 -*-
"""生成 R4 与 R5(auto) 的逐条语义对照表（Markdown）。

用法：
    python tools/r5_compare.py            # 40 条固定语料，intimate
    python tools/r5_compare.py --all-rel  # 三种关系全跑

只读本地 fixture，不触网；不改变任何状态（跑完把模式恢复成原值）。
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import intent_engine                                # noqa: E402
import sticker_engine                               # noqa: E402
from emotion_engine import analyze_context          # noqa: E402
from sticker_config import CONFIG                   # noqa: E402
from sticker_engine import search_sticker, set_library   # noqa: E402
from trigger_engine import should_send_sticker      # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "instructions.json")

sys.path.insert(0, os.path.join(ROOT, "tools"))
from freeze_baseline import CORPUS  # noqa: E402


def pick(ctx, rel="intimate"):
    if not should_send_sticker(ctx):
        return None
    return search_sticker(ctx, relationship=rel, deterministic=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all-rel", action="store_true")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    with open(FIXTURE, encoding="utf-8") as f:
        data = json.load(f)
    set_library(data)
    by_id = {item["id"]: item for item in data["stickers"]}

    original = CONFIG.intent_mode
    relationships = ["intimate", "friend", "formal"] if args.all_rel else ["intimate"]
    lines = []
    changed = total = 0

    for rel in relationships:
        lines.append("### relationship = `%s`\n" % rel)
        lines.append("| 用户表达 | R4 选图 | R5(auto) 选图 | 助手意图 | 图片行为 | 变化 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for text in CORPUS:
            CONFIG.intent_mode = "off"
            r4 = pick(analyze_context(text), rel)
            CONFIG.intent_mode = "auto"
            ctx = analyze_context(text)
            r5 = pick(ctx, rel)

            def cell(item):
                if item is None:
                    return "—"
                return "%s %s" % (item["id"], item["name"])

            behavior = "—"
            if r5 is not None:
                info = intent_engine.behaviors_for(r5)
                behavior = "%s（%s）" % ("/".join(info["behaviors"]), info["source"])
            r4_id = r4["id"] if r4 else None
            r5_id = r5["id"] if r5 else None
            total += 1
            if r4_id != r5_id:
                changed += 1
                delta = "**变**"
            else:
                delta = "同"
            lines.append("| %s | %s | %s | %s | %s | %s |" % (
                text, cell(r4), cell(r5), ctx.get("assistant_intent") or "—", behavior, delta))
        lines.append("")

    CONFIG.intent_mode = original
    header = [
        "# R5 语义对照样本",
        "",
        "- 图库：`instructions.json` v%s / %d 条" % (data.get("version"), len(data["stickers"])),
        "- R4 = `R5_INTENT_MODE=off`（冻结基准 `tests/fixtures/r4_baseline_samples.json`）",
        "- R5 = `R5_INTENT_MODE=auto`（意图参与打分）",
        "- 变化条数：%d / %d" % (changed, total),
        "",
    ]
    output = "\n".join(header + lines)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(output + "\n")
        print("wrote %s（变化 %d/%d）" % (args.out, changed, total))
    else:
        print(output)


if __name__ == "__main__":
    main()
