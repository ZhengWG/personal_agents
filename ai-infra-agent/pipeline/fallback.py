#!/usr/bin/env python3
"""超时兜底报告 —— 不依赖模型，把已抓到的 JSON 直接转成带链接的 Markdown。

用途：claude 被看门狗杀掉时，抓取阶段的产物其实已经落盘了（/tmp/ai-infra-<date>.json）。
与其发一封"失败"邮件、把一整天的料连同 dedup 状态一起浪费掉，不如把原始条目发出去。
质量当然不如模型总结过的（没有价值化一句话、没有归类、没有 TL;DR），但**有链接、能读、
不丢信息**，而且明确标注了它是降级产物。

输出格式刻意对齐 send_mail.py 的 md_to_html：emoji 开头的行会渲染成 <h2>，
`● ` 开头的行会渲染成带链接的 <li>。

Usage:
    python3 ai-infra-agent/agent.py fallback [--from /tmp/ai-infra-20260807.json]
                                       [--discover /tmp/ai-infra-discover-20260807.json]
                                       [--reason "看门狗超时"] [--out report.md]
    # --from 不给时自动找当天的 /tmp/ai-infra-<YYYYMMDD>.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    from . import paths
except ImportError:  # 直接执行本文件时
    import paths

MAX_PER_SECTION = 40


def load(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception as e:  # noqa: BLE001
        print(f"[fallback] 读不到 {path}: {e}", file=sys.stderr)
        return None


def esc(s: str) -> str:
    return " ".join(str(s or "").split())


def section(title: str, items: list[str]) -> list[str]:
    out = [title]
    if items:
        out.extend(items)
    else:
        out.append("● （本轮无条目 —— 可能是抓取失败，也可能是跨天去重已滤掉）")
    out.append("")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", default=None)
    ap.add_argument("--discover", default=None)
    ap.add_argument("--reason", default="claude 未能在超时前完成总结")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    today = paths.today(utc=False)
    src = Path(args.src) if args.src else paths.fetch_json(today)
    data = load(src)
    if data is None:
        sys.exit(f"FALLBACK FAILED: 没有可用的抓取结果（{src}）")

    disc = load(Path(args.discover)) if args.discover else None

    L: list[str] = []
    L.append(f"📋 AI 推理优化日报（降级版） — {today}")
    L.append("")
    L.append("📌 说明")
    L.append(f"这是一份**降级报告**：{args.reason}，因此跳过了模型的筛选、归类与价值化总结，")
    L.append("直接把本轮抓到的原始条目按来源列出。条目都带原始链接，可以自己扫。")
    L.append("完整版日报会在下一轮正常运行时恢复。")
    L.append("")

    # --- GitHub PR ---
    prs = data.get("github_prs") or []
    by_repo: dict[str, list[dict]] = {}
    for p in prs:
        by_repo.setdefault(p.get("repo", "?"), []).append(p)
    items: list[str] = []
    for repo, lst in sorted(by_repo.items(), key=lambda kv: -len(kv[1])):
        merged = [x for x in lst if x.get("merged")]
        opened = [x for x in lst if not x.get("merged")]
        items.append(f"{repo} — {len(lst)} 条（{len(merged)} merged）")
        for p in (merged + opened)[:12]:
            tag = "Merged" if p.get("merged") else "Open"
            items.append(f"● [{esc(p.get('title'))}]({p.get('url')}) 【{tag}】")
        if len(lst) > 12:
            rest = " · ".join(f"[#{x.get('num')}]({x.get('url')})" for x in (merged + opened)[12:32])
            items.append(f"● 其他 {len(lst) - 12} 条：{rest}")
    L += section("🔧 GitHub PR 动态", items[:MAX_PER_SECTION * 3])

    # --- Release ---
    rels = data.get("github_releases") or []
    L += section("🚀 版本发布", [
        f"● [{esc(r.get('repo'))} {esc(r.get('name'))}]({r.get('url')}) — {esc(r.get('published_at'))[:10]}"
        for r in rels[:MAX_PER_SECTION]])

    # --- 模型发布 ---
    models = data.get("hf_models") or []
    if models:
        L += section("🤗 模型 / 权重发布", [
            f"● [{esc(m.get('title'))}]({m.get('url')}) — ♥{m.get('likes', 0)}"
            for m in models[:MAX_PER_SECTION]])

    # --- 论文 ---
    papers = (data.get("papers_hf") or []) + (data.get("papers_arxiv") or [])
    L += section("📄 论文（未经推理相关性筛选）", [
        f"● [{esc(p.get('title'))}]({p.get('url')})"
        + (f" — 👍{p.get('votes')}" if p.get("votes") else "")
        for p in papers[:MAX_PER_SECTION]])

    # --- 博客 ---
    L += section("📰 博客与新闻", [
        f"● [{esc(b.get('title'))}]({b.get('url')}) — {esc(b.get('site'))}"
        for b in (data.get("blogs") or [])[:MAX_PER_SECTION]])

    # --- 社区 ---
    community = []
    for h in (data.get("hn") or [])[:20]:
        community.append(f"● [{esc(h.get('title'))}]({h.get('url')}) — HN {h.get('points')}⬆ {h.get('num_comments')}💬")
    for r in (data.get("reddit") or [])[:20]:
        community.append(f"● [{esc(r.get('title'))}]({r.get('url')}) — r/LocalLLaMA")
    L += section("💬 社区讨论", community)

    # --- 拓源 ---
    if disc:
        d_items = []
        for x in (disc.get("trending") or [])[:10]:
            d_items.append(f"● [{esc(x.get('repo'))}]({x.get('url')}) — {esc(x.get('desc'))} ｜ 发现于：Trending")
        for x in (disc.get("rising") or [])[:10]:
            d_items.append(f"● [{esc(x.get('repo'))}]({x.get('url')}) — {esc(x.get('desc'))} ｜ ★{x.get('stars')}")
        for x in (disc.get("awesome_new") or [])[:10]:
            d_items.append(f"● [{esc(x.get('repo'))}]({x.get('url')}) — 策展清单新增")
        terms = disc.get("new_terms") or []
        if terms:
            d_items.append("● 未识别的新术语（未经查证）：" + "、".join(
                f"{t.get('term')}×{t.get('count')}" for t in terms[:15]))
        L += section("🆕 新兴方向（原始候选，未经筛选）", d_items)

    counts = {k: len(v) for k, v in data.items() if isinstance(v, list)}
    L.append("---")
    L.append(f"降级报告 ｜ 抓取计数：{counts} ｜ 生成于 {datetime.now().isoformat(timespec='seconds')}")

    text = "\n".join(L) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"FALLBACK REPORT → {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
