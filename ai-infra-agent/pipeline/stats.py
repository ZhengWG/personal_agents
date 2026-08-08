#!/usr/bin/env python3
"""量报告的阅读量 —— 给 skill 做自检，避免日报越写越长。

只算**真正要读的字**：markdown 链接只算锚文本（URL 不读）、代码/标记不算、
`● ` 之类的项目符号不算。中文按字计，英文按词计（1 词 ≈ 2.5 字的阅读耗时）。

阅读速度取 400 字/分钟（中文技术内容的常见区间是 300–500，取中位偏保守）。

Usage:
    python3 ai-infra-agent/agent.py stats ai-infra-agent/reports/2026-08-08.md
    python3 ai-infra-agent/agent.py stats <报告> --budget 20     # 超预算时退出码 1
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CJK = re.compile(r"[㐀-鿿぀-ヿ]")
WORD = re.compile(r"[A-Za-z][A-Za-z0-9_.+#-]*")
CPM = 400  # 字/分钟
SECTION = r"^(?:#{1,3}\s*)?[📋📌⚡🔧🚀🤗📄📰💬🆕⭐📈]"


def readable_text(md: str) -> str:
    md = re.sub(r"```.*?```", " ", md, flags=re.S)          # 代码块不读
    md = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", md)        # 链接只留锚文本
    md = re.sub(r"<!--.*?-->", " ", md, flags=re.S)         # 注释
    md = re.sub(r"^[#>\-*●↳|]+\s*", "", md, flags=re.M)     # 行首标记
    md = re.sub(r"[*`_~|]", "", md)                          # 行内标记
    return md


def measure(md: str) -> dict:
    text = readable_text(md)
    cjk = len(CJK.findall(text))
    words = len(WORD.findall(text))
    # 英文一个词的阅读耗时约等于 2.5 个汉字
    effective = cjk + words * 2.5
    return {
        "cjk": cjk, "words": words, "effective": int(effective),
        "minutes": round(effective / CPM, 1),
        "bullets": len(re.findall(r"^●\s", md, re.M)),
        "links": len(re.findall(r"\[[^\]]+\]\(https?://", md)),
        # 标题两种写法都要认：`## 📌 …` 和裸 `📌 …`（骨架模板用的是后者）
        "sections": len(re.findall(SECTION, md, re.M)),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--budget", type=float, default=None,
                    help="阅读时间预算（分钟）；超了退出码 1")
    args = ap.parse_args()

    p = Path(args.report)
    if not p.is_file():
        sys.exit(f"报告不存在: {p}")
    m = measure(p.read_text(encoding="utf-8"))

    print(f"分类 {m['sections']} 节 ｜ 条目 {m['bullets']} 条 ｜ 链接 {m['links']} 个")
    print(f"正文 {m['cjk']} 汉字 + {m['words']} 英文词 → 折合 {m['effective']} 字")
    print(f"预计阅读时间：{m['minutes']} 分钟（按 {CPM} 字/分钟）")

    if args.budget is not None:
        if m["minutes"] > args.budget:
            over = m["minutes"] - args.budget
            print(f"\n⚠️ 超出预算 {over:.1f} 分钟 —— 需要砍掉约 "
                  f"{int(over * CPM)} 字（≈ {int(over * CPM / 60)} 个条目）", file=sys.stderr)
            sys.exit(1)
        print(f"✅ 在 {args.budget} 分钟预算内（余 {args.budget - m['minutes']:.1f} 分钟）")


if __name__ == "__main__":
    main()
