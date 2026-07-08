#!/usr/bin/env python3
"""Cross-day dedup state for daily-ai-infra.

Reads fetch_sources.py JSON on stdin, drops items already reported recently
(a GitHub PR re-surfaces only when its merged-state changes; papers/blogs/HN
once seen never repeat), records the survivors as seen-today, prunes entries
older than --prune-days, and writes the filtered JSON to stdout.

Usage:
    fetch_sources.py | dedup_state.py [--state PATH] [--prune-days 30] [--no-record]

--no-record: filter only, don't mutate state (useful for dry runs / tests).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

LIST_KEYS = ["github_prs", "github_releases", "papers_arxiv", "papers_hf",
             "hf_models", "hn", "reddit", "blogs"]


def sig(item: dict) -> str:
    """Re-surface signature: PRs change when merged; everything else is one-shot."""
    if item.get("source") == "github_pr":
        return "merged" if item.get("merged") else "open"
    return "x"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="ai-infra-agent/state/seen.json")
    ap.add_argument("--prune-days", type=int, default=30)
    ap.add_argument("--no-record", action="store_true")
    args = ap.parse_args()

    data = json.load(sys.stdin)
    sp = Path(args.state)
    sp.parent.mkdir(parents=True, exist_ok=True)
    state: dict = json.loads(sp.read_text()) if sp.is_file() else {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    kept_counts: dict[str, int] = {}
    dropped = 0
    for k in LIST_KEYS:
        keep = []
        for it in data.get(k, []) or []:
            iid = it.get("id")
            if not iid:
                keep.append(it)
                continue
            prev = state.get(iid)
            if prev and prev.get("sig") == sig(it):
                dropped += 1
                continue
            keep.append(it)
            if not args.no_record:
                state[iid] = {"sig": sig(it), "last_seen": today}
        data[k] = keep
        kept_counts[k] = len(keep)

    if not args.no_record:
        cutoff = (datetime.now(timezone.utc)
                  - timedelta(days=args.prune_days)).strftime("%Y-%m-%d")
        state = {i: v for i, v in state.items() if v.get("last_seen", "") >= cutoff}
        sp.write_text(json.dumps(state, ensure_ascii=False))

    data.setdefault("meta", {})["dedup"] = {
        "dropped": dropped, "kept": kept_counts, "state_size": len(state)}
    print(f"[dedup_state] dropped={dropped} kept={kept_counts} state={len(state)}",
          file=sys.stderr)
    json.dump(data, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
