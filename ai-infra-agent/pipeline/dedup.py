#!/usr/bin/env python3
"""Cross-day dedup state for daily-ai-infra —— 两阶段提交版。

读 agent.py fetch 的 JSON（stdin），丢掉**最近已经报过**的条目
（GitHub PR 只在 merged 状态翻转时重新出现；论文/博客/HN 见过就不再报），
把过滤后的 JSON 写到 stdout。

## 为什么要两阶段提交

旧版在过滤的同时就把条目写进 `seen.json`。问题：Step 1 落盘"已读"，但报告要到
十几分钟后才生成。中间任何一次崩溃（超时、session limit、手滑 kill）都会造成
**条目被标记为已读、报告却从没产出** —— 一整天的料就这么被吞掉，第二天也不会再出现。
这不是假想，2026-08-07 就这样连炸两轮。

所以拆成两步：

    阶段 1（过滤）  agent.py dedup            → 过滤 + 写 pending.json，**不碰 seen.json**
    阶段 2（提交）  agent.py dedup --commit   → 报告发出去之后，才把 pending 并进 seen.json

崩在中间 → pending 被下一轮直接覆盖，seen.json 从未被污染，条目原样重来。

Usage:
    agent.py fetch | agent.py dedup                    # 阶段 1
    agent.py dedup --commit                              # 阶段 2（发信成功后调用）
    agent.py fetch | agent.py dedup --no-record        # 只过滤，连 pending 都不写（dry run）
    agent.py dedup --purge-date 2026-08-07               # 运维：撤销某天的"已读"标记
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from . import paths
except ImportError:  # 直接执行本文件时
    import paths

LIST_KEYS = ["github_prs", "github_releases", "papers_arxiv", "papers_hf",
             "hf_models", "hn", "reddit", "blogs"]

DEFAULT_STATE = paths.SEEN_JSON
DEFAULT_PENDING = paths.PENDING_JSON


def sig(item: dict) -> str:
    """Re-surface signature: PRs change when merged; everything else is one-shot."""
    if item.get("source") == "github_pr":
        return "merged" if item.get("merged") else "open"
    return "x"


def load_state(p: Path) -> dict:
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception as e:  # noqa: BLE001
        print(f"[dedup] {p} 解析失败（{e}），当空状态处理", file=sys.stderr)
        return {}


def today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def cmd_commit(args) -> None:
    """阶段 2：报告已经发出去了，把 pending 并进 seen.json 并 prune。"""
    sp, pp = Path(args.state), Path(args.pending)
    pending = load_state(pp)
    if not pending:
        print("[dedup] pending 为空，无需提交", file=sys.stderr)
        return
    state = load_state(sp)
    state.update(pending)
    cutoff = (datetime.now(timezone.utc)
              - timedelta(days=args.prune_days)).strftime("%Y-%m-%d")
    before = len(state)
    state = {i: v for i, v in state.items() if v.get("last_seen", "") >= cutoff}
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(state, ensure_ascii=False))
    pp.unlink(missing_ok=True)
    print(f"[dedup] COMMITTED {len(pending)} 条 → seen.json "
          f"({before} → {len(state)}，prune 掉 {before - len(state)})", file=sys.stderr)


def cmd_purge(args) -> None:
    """运维：撤销某一天的'已读'标记（比如那天报告没发成）。"""
    sp = Path(args.state)
    state = load_state(sp)
    before = len(state)
    state = {i: v for i, v in state.items() if v.get("last_seen") != args.purge_date}
    sp.write_text(json.dumps(state, ensure_ascii=False))
    print(f"[dedup] PURGED last_seen={args.purge_date}: "
          f"{before} → {len(state)}（撤销 {before - len(state)} 条）", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=DEFAULT_STATE)
    ap.add_argument("--pending", default=DEFAULT_PENDING)
    ap.add_argument("--prune-days", type=int, default=30)
    ap.add_argument("--no-record", action="store_true",
                    help="只过滤，连 pending 都不写（dry run / 测试）")
    ap.add_argument("--commit", action="store_true",
                    help="阶段 2：把 pending 并进 seen.json（报告发出去之后调用）")
    ap.add_argument("--purge-date", default=None,
                    help="运维：撤销指定日期（YYYY-MM-DD）的已读标记")
    args = ap.parse_args()

    if args.commit:
        return cmd_commit(args)
    if args.purge_date:
        return cmd_purge(args)

    # --- 阶段 1：过滤 ---
    data = json.load(sys.stdin)
    state = load_state(Path(args.state))
    today = today_utc()

    pending: dict = {}
    kept_counts: dict[str, int] = {}
    dropped = 0
    for k in LIST_KEYS:
        keep = []
        for it in data.get(k, []) or []:
            iid = it.get("id")
            if not iid:
                keep.append(it)
                continue
            prev = state.get(iid)          # 只看 seen.json，pending 不参与过滤
            if prev and prev.get("sig") == sig(it):
                dropped += 1
                continue
            keep.append(it)
            pending[iid] = {"sig": sig(it), "last_seen": today}
        data[k] = keep
        kept_counts[k] = len(keep)

    if not args.no_record:
        pp = Path(args.pending)
        pp.parent.mkdir(parents=True, exist_ok=True)
        # 直接覆盖：上一轮崩溃残留的 pending 本来就该作废（那些条目从没被报过）
        pp.write_text(json.dumps(pending, ensure_ascii=False))

    data.setdefault("meta", {})["dedup"] = {
        "dropped": dropped, "kept": kept_counts,
        "state_size": len(state), "pending": len(pending),
        "committed": False,
    }
    print(f"[dedup] dropped={dropped} kept={kept_counts} "
          f"seen={len(state)} pending={len(pending)} "
          f"(未提交——发信成功后请跑 agent.py dedup --commit)", file=sys.stderr)
    json.dump(data, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
