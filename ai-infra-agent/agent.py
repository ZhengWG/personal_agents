#!/usr/bin/env python3
"""daily-ai-infra 的唯一 CLI 入口。

以前 skill 要记 5 个散落在 scripts/ 下的脚本路径；现在统一成子命令：

    agent.py fetch      抓核心盘 → 归一化 JSON（stdout）
    agent.py dedup      跨天去重（stdin→stdout），两阶段提交
    agent.py discover   拓源：Trending / awesome 增量 / 新术语
    agent.py fallback   把抓取 JSON 转成降级报告（不依赖模型）
    agent.py stats      量报告的阅读时间，超预算退出码 1

每个子命令的参数见 `agent.py <cmd> --help`。在哪个目录执行都可以
（路径由 pipeline/paths.py 从本文件位置反推）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline import dedup, discover, fallback, fetch, stats  # noqa: E402

COMMANDS = {
    "fetch": (fetch.main, "抓核心盘（GitHub/arXiv/HF/HN/Reddit/博客）→ JSON"),
    "dedup": (dedup.main, "跨天去重 + 两阶段提交（--commit / --purge-date）"),
    "discover": (discover.main, "拓源：Trending / awesome 增量 / 新术语识别"),
    "fallback": (fallback.main, "降级报告：把抓取 JSON 直接转成带链接的 Markdown"),
    "stats": (stats.main, "量报告阅读时间（--budget 20 超了退出码 1）"),
}


def usage(code: int = 0) -> None:
    print(__doc__.strip().split("\n\n")[0])
    print("\n用法: agent.py <命令> [参数...]\n\n命令:")
    for name, (_, desc) in COMMANDS.items():
        print(f"  {name:<10} {desc}")
    print("\n每个命令的详细参数: agent.py <命令> --help")
    sys.exit(code)


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        usage()
    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        print(f"未知命令: {cmd}\n", file=sys.stderr)
        usage(2)
    # 让子命令的 argparse 看到干净的 argv（prog 名带上子命令，报错信息才准确）
    sys.argv = [f"agent.py {cmd}", *sys.argv[2:]]
    COMMANDS[cmd][0]()


if __name__ == "__main__":
    main()
