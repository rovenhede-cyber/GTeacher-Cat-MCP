# -*- coding: utf-8 -*-
"""冻结一份「当前代码的选择结果」作为回归基准。

用法（在仓库根目录）：
    python tools/freeze_baseline.py            # 生成 tests/fixtures/r4_baseline_samples.json
    python tools/freeze_baseline.py out.json   # 指定输出

为什么需要它：R5 增加了 assistant_response_intent，会改变排序。为了让「off 模式必须
与 R4 逐条一致」这句话可验证，必须在改代码之前把 R4 的结果固化成文件；改完代码再生成
就没有意义了（那时的代码已经是 R5）。

注意：
- 只用 tests/fixtures/instructions.json（v3.0 / 77 条）离线跑，不触网。
- 只记录「选中哪张图」和「闸门是否放行」，不记录原始文本的命中词。
"""
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from emotion_engine import analyze_context          # noqa: E402
from sticker_engine import search_sticker, set_library   # noqa: E402
from trigger_engine import should_send_sticker      # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "instructions.json")

# 固定语料：覆盖情绪自述、庆祝、安慰、亲密动作、技术任务、危机、玩笑、无信号、
# 关系敏感（媳妇）、显式索图。顺序固定，绝不随时间改动——要加就往后追加。
CORPUS = [
    "今天好开心",
    "终于通过了考试，太开心了",
    "实验又失败了，好难受",
    "抱抱我",
    "想亲亲你",
    "给你比心",
    "送花给你",
    "我要单膝跪地求婚，把戒指给你",
    "谢谢你一直帮我",
    "哈哈你怎么又迟到了，狗头",
    "今天下午三点开会",
    "嗯",
    "有点委屈",
    "唉，好累",
    "我真的不想活了",
    "这个 API 报 500，怎么排查",
    "论文写不出来，好崩溃",
    "我有点生气",
    "我真的很生气",
    "我真的气死了！！",
    "宝宝，我今天好生气",
    "我爱你，媳妇～",
    "想死你了，什么时候回来",
    "我今天被领导骂了，好委屈",
    "明天要答辩了，好紧张",
    "我一直加班到凌晨，扛不住了",
    "这幅画好看吗",
    "哈哈笑死我了",
    "好困，先睡了晚安",
    "我真的服了，这破系统又崩了",
    "我们吵架了，他动手了，我很害怕",
    "医生说我需要住院观察",
    "今天天气不错",
    "我拿到 offer 了！",
    "你能教我怎么做这个吗",
    "帮我写一个脚本",
    "我好羡慕你",
    "我觉得自己很失败",
    "你给我等着，狗头",
    "收到，马上处理",
]

RELATIONSHIPS = ("intimate", "friend", "formal")


def git(*args):
    try:
        return subprocess.run(["git", "-C", ROOT, *args], capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return ""


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "tests", "fixtures", "r4_baseline_samples.json")

    with open(FIXTURE, encoding="utf-8") as f:
        raw = f.read()
    data = json.loads(raw)
    set_library(data)

    samples = []
    for text in CORPUS:
        for rel in RELATIONSHIPS:
            ctx = analyze_context(text)
            gate = bool(should_send_sticker(ctx))
            item = search_sticker(ctx, relationship=rel, deterministic=True) if gate else None
            samples.append({
                "text": text,
                "relationship": rel,
                "gate": gate,
                "id": item["id"] if item else None,
            })

    payload = {
        "meta": {
            "stage": "R4",
            "note": "改代码之前冻结的选择结果；off 模式必须逐条一致",
            "git_rev": git("rev-parse", "--short", "HEAD"),
            "git_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "library_version": data.get("version"),
            "library_count": len(data.get("stickers", [])),
            # 归一化 CRLF 后再算：autocrlf / git archive 会改变磁盘字节但内容不变
            "library_md5": hashlib.md5(raw.replace("\r\n", "\n").encode("utf-8")).hexdigest(),
            "library_md5_note": "CRLF 归一化后计算",
            "corpus_size": len(CORPUS),
            "relationships": list(RELATIONSHIPS),
        },
        "samples": samples,
    }

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")

    gates = sum(1 for s in samples if s["gate"])
    hits = sum(1 for s in samples if s["id"])
    print("wrote %s" % out_path)
    print("samples=%d gate_passed=%d selected=%d" % (len(samples), gates, hits))


if __name__ == "__main__":
    main()
