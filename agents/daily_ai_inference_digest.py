#!/usr/bin/env python3
"""Generate daily AI inference optimization digest."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import textwrap
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


DEFAULT_MODEL = "gpt-4.1-mini"
DEFAULT_API_BASE = "https://api.openai.com/v1"
DEFAULT_OUTPUT_DIR = "agent_outputs"
DEFAULT_GITHUB_REPOS = "sgl-project/sglang,vllm-project/vllm"
DEFAULT_ARXIV_QUERY = (
    '(all:"inference" OR all:"speculative decoding" OR all:"kv cache" '
    'OR all:"mixture of experts" OR all:"quantization") AND (cat:cs.CL OR cat:cs.LG)'
)
DEFAULT_NEWS_FEEDS = ",".join(
    [
        "OpenAI|https://openai.com/news/rss.xml",
        "HuggingFace|https://huggingface.co/blog/feed.xml",
        "InterconnectsAI|https://www.interconnects.ai/rss/",
        "DEV-AI|https://dev.to/feed/tag/ai",
    ]
)
DEFAULT_SUBREDDITS = "LocalLLaMA"
DEFAULT_LOOKBACK_HOURS = 48

SYSTEM_PROMPT = (
    "你是资深 AI 推理工程情报分析助手。"
    "你会基于输入数据生成“AI 推理优化日报”，输出必须是简体中文 Markdown。"
    "不要编造不存在的条目，所有结论要来自提供的数据。"
    "结构必须严格包含且按顺序输出："
    "[YYYY-MM-DD] AI 推理优化日报, "
    "📋 AI 推理优化日报 — YYYY-MM-DD, "
    "🔧 GitHub PR 动态, "
    "📄 值得关注的论文, "
    "📰 博客与新闻, "
    "💬 社区讨论, "
    "⭐ 今日重点推荐。"
    "每个条目建议使用“标题 — 作者/来源 — 一句话价值说明”的格式。"
)

USER_AGENT = "personal-agents-daily-digest/1.0"


def getenv_str(name: str, default: str) -> str:
    value = (os.getenv(name) or "").strip()
    return value or default


def getenv_int(name: str, default: int) -> int:
    value = (os.getenv(name) or "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily AI inference digest agent")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use built-in mock data (no network call, no model call).",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip model synthesis and render deterministic markdown from fetched data.",
    )
    parser.add_argument(
        "--date",
        help="Digest date in YYYY-MM-DD (default: current UTC date).",
    )
    return parser.parse_args()


def http_get(url: str, headers: dict[str, str] | None = None) -> bytes:
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url=url, method="GET", headers=req_headers)
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()


def safe_fetch_json(url: str, headers: dict[str, str] | None = None) -> dict | list:
    try:
        body = http_get(url, headers=headers)
        return json.loads(body.decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
        return {}


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_feeds(value: str) -> list[tuple[str, str]]:
    feeds: list[tuple[str, str]] = []
    for item in parse_csv(value):
        if "|" in item:
            name, url = item.split("|", 1)
            feeds.append((name.strip(), url.strip()))
    return feeds


def truncate_items(items: list[dict], key: str, width: int) -> list[dict]:
    trimmed: list[dict] = []
    for item in items:
        updated = dict(item)
        text = str(updated.get(key, ""))
        updated[key] = textwrap.shorten(text, width=width, placeholder="...")
        trimmed.append(updated)
    return trimmed


def to_iso(ts: str) -> dt.datetime:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def fetch_github_prs(repo: str, limit: int, lookback_hours: int, token: str) -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "state": "open",
            "sort": "updated",
            "direction": "desc",
            "per_page": str(limit),
        }
    )
    url = f"https://api.github.com/repos/{repo}/pulls?{params}"
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = safe_fetch_json(url, headers=headers)
    if not isinstance(payload, list):
        return []

    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(hours=lookback_hours)
    rows: list[dict] = []
    for pr in payload:
        try:
            updated_at = to_iso(pr.get("updated_at", ""))
        except (TypeError, ValueError):
            continue
        if updated_at < cutoff:
            continue
        rows.append(
            {
                "repo": repo,
                "number": pr.get("number"),
                "title": (pr.get("title") or "").strip(),
                "author": (pr.get("user") or {}).get("login", "unknown"),
                "url": pr.get("html_url", ""),
                "updated_at": pr.get("updated_at", ""),
            }
        )
    return rows


def fetch_arxiv(query: str, limit: int) -> list[dict]:
    encoded = urllib.parse.quote(query, safe="")
    url = (
        "https://export.arxiv.org/api/query?"
        f"search_query={encoded}&start=0&max_results={limit}&sortBy=submittedDate&sortOrder=descending"
    )
    try:
        raw_xml = http_get(url).decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError, UnicodeDecodeError):
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError:
        return []

    papers: list[dict] = []
    for entry in root.findall("atom:entry", ns):
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        summary = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip()
        paper_id = (entry.findtext("atom:id", default="", namespaces=ns) or "").strip()
        published = (entry.findtext("atom:published", default="", namespaces=ns) or "").strip()
        authors = [
            (author.findtext("atom:name", default="", namespaces=ns) or "").strip()
            for author in entry.findall("atom:author", ns)
        ]
        if not title or not paper_id:
            continue
        papers.append(
            {
                "title": " ".join(title.split()),
                "summary": " ".join(summary.split()),
                "url": paper_id,
                "published": published,
                "authors": [a for a in authors if a],
            }
        )
    return papers


def fetch_rss(feed_name: str, feed_url: str, limit: int) -> list[dict]:
    try:
        raw = http_get(feed_url)
    except (urllib.error.URLError, urllib.error.HTTPError):
        return []

    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []

    items: list[dict] = []
    channel = root.find("channel")
    if channel is not None:
        rss_items = channel.findall("item")
        for item in rss_items[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            if title and link:
                items.append(
                    {
                        "source": feed_name,
                        "title": title,
                        "url": link,
                        "published": pub_date,
                    }
                )
        return items

    atom_ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", atom_ns)
    for entry in entries[:limit]:
        title = (entry.findtext("atom:title", default="", namespaces=atom_ns) or "").strip()
        published = (
            entry.findtext("atom:published", default="", namespaces=atom_ns)
            or entry.findtext("atom:updated", default="", namespaces=atom_ns)
            or ""
        ).strip()
        url = ""
        for link in entry.findall("atom:link", atom_ns):
            href = (link.get("href") or "").strip()
            rel = (link.get("rel") or "alternate").strip()
            if href and rel in ("alternate", ""):
                url = href
                break
        if title and url:
            items.append(
                {
                    "source": feed_name,
                    "title": title,
                    "url": url,
                    "published": published,
                }
            )
    return items


def fetch_reddit(subreddit: str, limit: int) -> list[dict]:
    url = f"https://www.reddit.com/r/{subreddit}/new.json?limit={limit}"
    payload = safe_fetch_json(url)
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    children = data.get("children", []) if isinstance(data, dict) else []
    posts: list[dict] = []
    for child in children:
        post = child.get("data", {}) if isinstance(child, dict) else {}
        title = (post.get("title") or "").strip()
        if not title:
            continue
        permalink = (post.get("permalink") or "").strip()
        posts.append(
            {
                "source": f"Reddit r/{subreddit}",
                "title": title,
                "url": f"https://www.reddit.com{permalink}" if permalink else "",
                "author": post.get("author", "unknown"),
                "created_utc": post.get("created_utc"),
            }
        )
    return posts


def mock_dataset(today: str) -> dict:
    return {
        "date": today,
        "github_prs": [
            {
                "repo": "sgl-project/sglang",
                "number": 12345,
                "title": "Add speculative decode fallback for short context",
                "author": "example-dev",
                "url": "https://github.com/sgl-project/sglang/pull/12345",
                "updated_at": f"{today}T08:00:00Z",
            },
            {
                "repo": "vllm-project/vllm",
                "number": 67890,
                "title": "Improve KV cache eviction metrics",
                "author": "example-maintainer",
                "url": "https://github.com/vllm-project/vllm/pull/67890",
                "updated_at": f"{today}T07:20:00Z",
            },
        ],
        "papers": [
            {
                "title": "MARS: Multi-Token Generation for AR Models",
                "summary": "Zero-parameter approach for faster decoding in autoregressive models.",
                "url": "https://arxiv.org/abs/2604.07023",
                "published": f"{today}T03:00:00Z",
                "authors": ["Author A", "Author B"],
            }
        ],
        "news": [
            {
                "source": "OpenAI",
                "title": "Enterprise case study: using Codex in production",
                "url": "https://openai.com/",
                "published": today,
            }
        ],
        "community": [
            {
                "source": "Reddit r/LocalLLaMA",
                "title": "New sparse MoE model for edge deployment",
                "url": "https://www.reddit.com/r/LocalLLaMA/",
                "author": "demo-user",
                "created_utc": 0,
            }
        ],
    }


def build_input_dataset(today: str) -> dict:
    github_repos = parse_csv(getenv_str("TRACKED_GITHUB_REPOS", DEFAULT_GITHUB_REPOS))
    news_feeds = parse_feeds(getenv_str("TRACKED_NEWS_FEEDS", DEFAULT_NEWS_FEEDS))
    subreddits = parse_csv(getenv_str("TRACKED_SUBREDDITS", DEFAULT_SUBREDDITS))
    lookback_hours = getenv_int("GITHUB_LOOKBACK_HOURS", DEFAULT_LOOKBACK_HOURS)
    github_limit = getenv_int("GITHUB_PR_LIMIT", 10)
    arxiv_limit = getenv_int("ARXIV_LIMIT", 10)
    feed_limit = getenv_int("NEWS_FEED_LIMIT", 6)
    reddit_limit = getenv_int("REDDIT_LIMIT", 6)
    github_token = os.getenv("GITHUB_TOKEN", "").strip()
    arxiv_query = getenv_str("ARXIV_QUERY", DEFAULT_ARXIV_QUERY)

    github_prs: list[dict] = []
    for repo in github_repos:
        github_prs.extend(
            fetch_github_prs(
                repo=repo,
                limit=github_limit,
                lookback_hours=lookback_hours,
                token=github_token,
            )
        )

    papers = fetch_arxiv(query=arxiv_query, limit=arxiv_limit)
    news: list[dict] = []
    for name, url in news_feeds:
        news.extend(fetch_rss(feed_name=name, feed_url=url, limit=feed_limit))
    community: list[dict] = []
    for sub in subreddits:
        community.extend(fetch_reddit(subreddit=sub, limit=reddit_limit))

    github_prs = truncate_items(github_prs, key="title", width=120)
    papers = truncate_items(papers, key="title", width=140)
    papers = truncate_items(papers, key="summary", width=320)
    news = truncate_items(news, key="title", width=140)
    community = truncate_items(community, key="title", width=140)

    return {
        "date": today,
        "github_prs": github_prs,
        "papers": papers,
        "news": news,
        "community": community,
    }


def extract_text_from_response(payload: dict) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    chunks: list[str] = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                chunks.append(content["text"])
    return "\n".join(chunks).strip()


def synthesize_with_llm(dataset: dict, model: str, api_key: str, api_base: str) -> str:
    endpoint = f"{api_base.rstrip('/')}/responses"
    user_prompt = (
        "请将以下 JSON 数据整理成日报，保留关键细节，避免冗余：\n\n"
        f"{json.dumps(dataset, ensure_ascii=False, indent=2)}\n\n"
        "要求："
        "1) 每个区块至少输出 3 条（如果数据不足，就尽可能输出并说明数据不足）；"
        "2) PR 动态要体现仓库名、PR 号、作者和价值；"
        "3) 最后“今日重点推荐”给出 3 条；"
        "4) 禁止杜撰不在 JSON 中的信息。"
    )
    body = {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "text", "text": SYSTEM_PROMPT}]},
            {"role": "user", "content": [{"type": "text", "text": user_prompt}]},
        ],
        "temperature": 0.2,
        "max_output_tokens": 2600,
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error: HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAI API connection error: {exc}") from exc

    text = extract_text_from_response(payload)
    if not text:
        raise RuntimeError("Model returned empty content.")
    return text


def looks_like_digest(markdown: str) -> bool:
    required = [
        "AI 推理优化日报",
        "🔧 GitHub PR 动态",
        "📄 值得关注的论文",
        "📰 博客与新闻",
        "💬 社区讨论",
        "⭐ 今日重点推荐",
    ]
    return all(token in markdown for token in required)


def repo_display_name(repo: str) -> str:
    mapping = {
        "sgl-project/sglang": "SGLang",
        "vllm-project/vllm": "vLLM",
    }
    return mapping.get(repo, repo.split("/")[-1] or repo)


def infer_pr_value(title: str) -> str:
    lower = title.lower()
    if "fix" in lower or "bug" in lower:
        return "修复稳定性/正确性问题，建议尽快评估是否影响线上推理。"
    if "speculative" in lower or "mtp" in lower:
        return "涉及投机解码/多 token 预测，可能直接提升吞吐与时延表现。"
    if "quant" in lower or "fp8" in lower or "int4" in lower:
        return "量化链路优化，重点关注精度-性能权衡与硬件兼容性。"
    if "kv" in lower or "cache" in lower:
        return "涉及 KV cache 管理，可能影响长上下文成本与稳定性。"
    if "moe" in lower:
        return "MoE 路由或并行后端改动，关注专家负载与通信开销。"
    if "attention" in lower:
        return "注意力内核/后端优化，可能带来直接推理性能收益。"
    return "推理基础设施改进，建议结合业务模型做回归验证。"


def paper_id(url: str) -> str:
    tail = url.rstrip("/").split("/")[-1]
    return tail or url


def deterministic_render(dataset: dict) -> str:
    date_str = dataset["date"]
    lines: list[str] = [
        f"[{date_str}] AI 推理优化日报",
        f"📋 AI 推理优化日报 — {date_str}",
        "",
        "🔧 GitHub PR 动态",
    ]
    prs = sorted(dataset.get("github_prs", []), key=lambda x: x.get("updated_at", ""), reverse=True)
    if prs:
        grouped: dict[str, list[dict]] = {}
        for pr in prs:
            grouped.setdefault(pr.get("repo", "unknown"), []).append(pr)
        for repo, repo_prs in grouped.items():
            lines.append(f"{repo_display_name(repo)} ({repo})")
            for pr in repo_prs[:10]:
                lines.append(
                    f"PR #{pr['number']} {pr['title']} — @{pr['author']} — {infer_pr_value(pr['title'])}"
                )
    else:
        lines.append("- 今日未抓取到满足窗口条件的 PR 数据。")

    lines.append("")
    lines.append("📄 值得关注的论文")
    papers = dataset.get("papers", [])
    if papers:
        for paper in papers[:12]:
            summary = paper.get("summary", "")
            summary = textwrap.shorten(summary, width=120, placeholder="...")
            lines.append(f"{paper['title']} ({paper_id(paper['url'])}) — {summary}")
    else:
        lines.append("- 今日未抓取到论文数据。")

    lines.append("")
    lines.append("📰 博客与新闻")
    news = dataset.get("news", [])
    if news:
        for item in news[:12]:
            lines.append(f"{item['source']}：{item['title']} — {item['url']}")
    else:
        lines.append("- 今日未抓取到博客/新闻数据。")

    lines.append("")
    lines.append("💬 社区讨论")
    community = dataset.get("community", [])
    if community:
        for post in community[:12]:
            lines.append(f"{post['source']}：{post['title']} — {post.get('url', '')}")
    else:
        lines.append("- 今日未抓取到社区讨论数据。")

    lines.append("")
    lines.append("⭐ 今日重点推荐")
    top_pr = prs[0] if prs else None
    top_paper = papers[0] if papers else None
    top_signal = (community[0] if community else (news[0] if news else None))
    if top_pr:
        lines.append(
            f"- {repo_display_name(top_pr['repo'])} PR #{top_pr['number']}：{top_pr['title']} — {infer_pr_value(top_pr['title'])}"
        )
    else:
        lines.append("- 今日暂无高优先级 PR 重点推荐（数据不足）。")
    if top_paper:
        lines.append(
            f"- 论文 {paper_id(top_paper['url'])}：{top_paper['title']} — 建议评估其在现有推理栈中的可落地性。"
        )
    else:
        lines.append("- 今日暂无论文重点推荐（数据不足）。")
    if top_signal:
        lines.append(
            f"- 社区/新闻信号：{top_signal.get('title', 'N/A')} — 建议跟踪后续工程实现与复现反馈。"
        )
    else:
        lines.append("- 今日暂无社区/新闻重点推荐（数据不足）。")
    return "\n".join(lines).strip()


def write_outputs(output_dir: pathlib.Path, date_str: str, markdown: str, dataset: dict) -> tuple[pathlib.Path, pathlib.Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
    md_path = output_dir / f"ai-inference-digest-{date_str}-{ts}.md"
    json_path = output_dir / f"ai-inference-digest-{date_str}-{ts}.json"
    md_path.write_text(markdown + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return md_path, json_path


def main() -> int:
    args = parse_args()
    date_str = args.date or dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    output_dir = pathlib.Path(os.getenv("AGENT_OUTPUT_DIR", DEFAULT_OUTPUT_DIR))
    model = (os.getenv("AGENT_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    api_base = (os.getenv("OPENAI_API_BASE") or DEFAULT_API_BASE).strip() or DEFAULT_API_BASE
    api_key = os.getenv("OPENAI_API_KEY", "").strip()

    if args.dry_run:
        dataset = mock_dataset(today=date_str)
        markdown = deterministic_render(dataset)
    else:
        dataset = build_input_dataset(today=date_str)
        if args.no_llm or not api_key:
            markdown = deterministic_render(dataset)
        else:
            markdown = synthesize_with_llm(
                dataset=dataset,
                model=model,
                api_key=api_key,
                api_base=api_base,
            )
            if not looks_like_digest(markdown):
                # Keep the pipeline robust when model formatting drifts.
                markdown = deterministic_render(dataset)

    md_file, json_file = write_outputs(output_dir, date_str, markdown, dataset)
    print(f"Generated markdown: {md_file}")
    print(f"Saved raw dataset: {json_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
