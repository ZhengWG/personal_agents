#!/usr/bin/env python3
"""Robust ingestion for the daily-ai-infra agent.

Fetches AI-inference-infra signal from free APIs/feeds and prints normalized
JSON to stdout (per-source counts to stderr). Claude consumes the JSON and does
the smart part (relevance filtering, value summaries, clustering, TL;DR).

Sources: GitHub (PRs via batched search + releases), arXiv (cs.LG/DC/AR/PF/CL/OS,
inference-keyword-filtered), HuggingFace Daily Papers, Hacker News (Algolia),
Reddit r/LocalLLaMA (RSS), blog RSS. Every source is fault-tolerant — a failing
source returns [] and logs a warning, never aborts the run. Honors HTTPS_PROXY.

Self-updating repo list (daily mode): the tracked repos live in
ai-infra-agent/config/repos.json. Each run also (a) discovers trending repos via
GitHub topic search and (b) tallies github.com/<owner>/<repo> mentions across all
fetched text; a candidate is auto-promoted to `tracked` once it's seen in
`promote_runs` runs or `promote_items` times in one run. Edit repos.json by hand
anytime — `tracked[].prs=false` makes a high-volume repo releases-only.

Usage:
    python3 agent.py fetch [--mode daily|range] [--since 2d|6mo|1y|YYYY-MM-DD]
                             [--config PATH] [--no-update-repos] [--pretty]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from . import paths, http as _http
except ImportError:  # 直接执行本文件时
    import paths, http as _http
from xml.etree import ElementTree as ET

UA = "ai-infra-agent/0.3 (+https://github.com/personal-agents)"
CONFIG_PATH = paths.REPOS_JSON

# Fallback repo spine if the config file is missing.
DEFAULT_TRACKED = [
    {"repo": "sgl-project/sglang", "prs": True, "releases": True},
    {"repo": "vllm-project/vllm", "prs": True, "releases": True},
    {"repo": "vllm-project/vllm-omni", "prs": True, "releases": True},
    {"repo": "sgl-project/sglang-omni", "prs": True, "releases": True},
]

# RSS/Atom blog feeds (best-effort; failures are skipped). Verified working.
# LMSYS/SGLang blog (https://lmsys.org/blog/) has NO RSS — the skill WebFetches it.
BLOG_FEEDS = [
    ("HuggingFace", "https://huggingface.co/blog/feed.xml"),
    ("vLLM", "https://vllm.ai/blog/rss.xml"),
    ("Interconnects", "https://www.interconnects.ai/feed"),
    ("PyTorch", "https://pytorch.org/blog/feed.xml"),
    ("NVIDIA-GenAI", "https://developer.nvidia.com/blog/category/generative-ai/feed/"),
    ("TogetherAI", "https://www.together.ai/blog/rss.xml"),
    ("Modal", "https://modal.com/blog/atom.xml"),
    ("Anyscale", "https://www.anyscale.com/rss.xml"),
    ("CharacterAI", "https://blog.character.ai/rss/"),
    ("llm-d", "https://llm-d.ai/blog/rss.xml"),
    ("RedHatDev", "https://developers.redhat.com/blog/feed"),
]

HN_TERMS = ["vLLM", "SGLang", "TensorRT-LLM", "LLM inference", "KV cache",
            "speculative decoding", "quantization LLM"]

# arXiv recent is mostly noise for an inference digest; keep only papers whose
# title/abstract hits an inference-infra term. Permissive on purpose.
ARXIV_CATS = ["cs.LG", "cs.DC", "cs.AR", "cs.PF", "cs.CL", "cs.OS"]
ARXIV_KEYWORDS = re.compile(
    r"inference|serv(e|ing)|kv[\s-]?cache|quantiz|speculative|throughput|latency|"
    r"\battention\b|mixture[- ]of[- ]experts|\bmoe\b|prefill|decod(e|ing)|kernel|"
    r"flash[\s-]?attention|tensor[\s-]?parallel|expert[\s-]?parallel|disaggregat|"
    r"batching|vllm|sglang|tensorrt|paged|radix|fp8|int4|int8|low[\s-]?bit|"
    r"sparsit|prun(e|ing)|distill|\bgpu\b|memory[\s-]?bandwidth|long[\s-]?context",
    re.I)

ATOM = "{http://www.w3.org/2005/Atom}"
REPO_RE = re.compile(r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)")
# infra-relevance gate for org-watch auto-tracking (drops awesome-lists, OCR, apps)
INFRA_KW = re.compile(
    r"infer|serv|kernel|gemm|attention|\bmla\b|\bmoe\b|expert|parallel|pipeline|"
    r"\bkv\b|cache|quant|spec|decod|prefill|throughput|latency|cuda|\bgpu\b|fp8|"
    r"nvlink|disagg|batch|radix|flash|tensor|\btrt\b", re.I)


def warn(msg: str) -> None:
    print(f"[fetch] {msg}", file=sys.stderr)


# HTTP 走共享层（带重试 + 退避），函数名保持不变，调用点无需改动
http_get = _http.get
http_json = _http.get_json


def parse_since(s: str) -> str:
    s = s.strip().lower()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    m = re.fullmatch(r"(\d+)\s*(d|w|mo|m|y)", s)
    if not m:
        raise ValueError(f"bad --since: {s!r} (use 2d / 3w / 6mo / 1y / YYYY-MM-DD)")
    n, unit = int(m.group(1)), m.group(2)
    days = {"d": 1, "w": 7, "mo": 30, "m": 30, "y": 365}[unit]
    return (datetime.now(timezone.utc) - timedelta(days=n * days)).strftime("%Y-%m-%d")


def chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# ----------------------------------------------------------- repo config ----

def load_repos(path: str) -> dict:
    p = Path(path)
    if p.is_file():
        try:
            cfg = json.loads(p.read_text())
            cfg.setdefault("tracked", DEFAULT_TRACKED)
            cfg.setdefault("candidates", {})
            cfg.setdefault("ignore", [])
            cfg.setdefault("discovery", {})
            return cfg
        except Exception as e:  # noqa: BLE001
            warn(f"repos.json parse failed ({e}); using default spine")
    return {"tracked": DEFAULT_TRACKED, "candidates": {}, "ignore": [], "discovery": {}}


def save_repos(path: str, cfg: dict) -> None:
    try:
        Path(path).write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
    except Exception as e:  # noqa: BLE001
        warn(f"could not persist repos.json: {e}")


# ---------------------------------------------------------------- GitHub ----

def gh_headers() -> dict:
    h = {"Accept": "application/vnd.github+json"}
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def fetch_github_prs(repos: list[str], since: str, mode: str) -> list[dict]:
    """Batched GitHub search: multiple repo: qualifiers per query → few API calls."""
    out: list[dict] = []
    qual = "is:merged merged" if mode == "range" else "updated"
    for i, chunk in enumerate(chunks(repos, 5)):
        if i:
            time.sleep(1)  # stay under search API's 10 req/min
        try:
            q = " ".join(f"repo:{r}" for r in chunk) + f" type:pr {qual}:>={since}"
            url = "https://api.github.com/search/issues?" + urllib.parse.urlencode(
                {"q": q, "sort": "updated", "order": "desc", "per_page": 100})
            for it in http_json(url, gh_headers()).get("items", []):
                pr = it.get("pull_request") or {}
                repo = (it.get("repository_url", "")).split("/repos/")[-1]
                out.append({
                    "source": "github_pr", "repo": repo,
                    "id": f"{repo}#{it['number']}", "num": it["number"],
                    "title": it["title"].strip(), "url": it["html_url"],
                    "state": it.get("state"), "merged": bool(pr.get("merged_at")),
                    "author": (it.get("user") or {}).get("login"),
                    "labels": [l["name"] for l in it.get("labels", [])],
                    "updated_at": it.get("updated_at"),
                })
        except Exception as e:  # noqa: BLE001
            warn(f"github_prs chunk {chunk} failed: {e}")
    return out


def fetch_github_releases(repos: list[str], since: str) -> list[dict]:
    out: list[dict] = []
    for repo in repos:
        try:
            url = f"https://api.github.com/repos/{repo}/releases?per_page=20"
            for rel in http_json(url, gh_headers()):
                pub = rel.get("published_at") or ""
                if pub[:10] < since:
                    continue
                out.append({
                    "source": "github_release", "repo": repo,
                    "id": f"{repo}@{rel.get('tag_name')}", "tag": rel.get("tag_name"),
                    "name": rel.get("name") or rel.get("tag_name"),
                    "url": rel.get("html_url"), "published_at": pub,
                    "body_excerpt": (rel.get("body") or "").strip()[:1500],
                })
        except Exception as e:  # noqa: BLE001
            warn(f"github_releases {repo} failed: {e}")
    return out


def org_watch(cfg: dict, tracked_names: set, active_days: int = 180) -> list[str]:
    """Auto-track infra-relevant repos from trusted orgs (dynamic hot-repo tracking).
    e.g. orgs=["deepseek-ai"] → new DeepEP/DeepGEMM/DeepSpec-style repos appear on their own."""
    disc = cfg.get("discovery") or {}
    orgs = disc.get("orgs") or []
    min_stars = int(disc.get("org_min_stars", 100))
    ignore = set(cfg.get("ignore") or [])
    cutoff = (datetime.now(timezone.utc) - timedelta(days=active_days)).strftime("%Y-%m-%d")
    added: list[str] = []
    for org in orgs:
        try:
            url = f"https://api.github.com/orgs/{org}/repos?sort=pushed&per_page=40"
            for r in http_json(url, gh_headers()):
                name = r.get("full_name", "")
                short = name.split("/")[-1].lower()
                desc = r.get("description") or ""
                if (not name or name in tracked_names or short in ignore
                        or short.startswith("awesome")
                        or (r.get("stargazers_count", 0) < min_stars)
                        or (r.get("pushed_at", "")[:10] < cutoff)
                        or not INFRA_KW.search(f"{name} {desc}")):
                    continue
                cfg["tracked"].append({"repo": name, "prs": True, "releases": True})
                tracked_names.add(name)
                added.append(name)
        except Exception as e:  # noqa: BLE001
            warn(f"org_watch {org} failed: {e}")
    return added


def load_awesome(cfg: dict) -> set:
    """Harvest curated awesome-list READMEs → set of repo names (a 'hot repo' allowlist)."""
    out: set = set()
    for lst in (cfg.get("discovery") or {}).get("awesome_lists") or []:
        for branch in ("main", "master"):
            try:
                md = http_get(
                    f"https://raw.githubusercontent.com/{lst}/{branch}/README.md"
                ).decode("utf-8", "ignore")
                for m in REPO_RE.findall(md):
                    out.add(m[:-4] if m.endswith(".git") else m)
                break
            except Exception as e:  # noqa: BLE001
                if branch == "master":
                    warn(f"awesome {lst} failed: {e}")
    return out


def tally_and_promote(cfg: dict, blob: str, tracked_names: set, today: str,
                      awesome: set | None = None) -> list[str]:
    """Count github.com/<repo> mentions in `blob`, bump candidates, promote hot ones.
    A repo on the curated awesome-list promotes faster (curated + mentioned twice)."""
    disc = cfg.get("discovery") or {}
    promote_runs = int(disc.get("promote_runs", 3))
    promote_items = int(disc.get("promote_items", 4))
    ignore = set(cfg.get("ignore") or [])
    cands = cfg.setdefault("candidates", {})
    counts: dict[str, int] = {}
    for m in REPO_RE.findall(blob or ""):
        name = m[:-4] if m.endswith(".git") else m
        short = name.split("/")[-1].lower()
        if name in tracked_names or short in ignore or name.count("/") != 1:
            continue
        counts[name] = counts.get(name, 0) + 1
    promoted = []
    for name, c in counts.items():
        if c < 2 and not (awesome and name in awesome):
            continue  # ignore one-off mentions (noise); need 2+ in a run, or be curated
        e = cands.setdefault(name, {"mentions_total": 0, "runs_seen": 0, "source": "mention"})
        e["mentions_total"] = e.get("mentions_total", 0) + c
        e["runs_seen"] = e.get("runs_seen", 0) + 1
        e["last_seen"] = today
        curated = bool(awesome) and name in awesome
        if curated:
            e["curated"] = True
        if (e["runs_seen"] >= promote_runs or c >= promote_items
                or (curated and c >= 2)):
            promoted.append(name)
    for name in promoted:
        cfg["tracked"].append({"repo": name, "prs": True, "releases": True})
        cands.pop(name, None)
        tracked_names.add(name)
    return promoted


# ---------------------------------------------------------------- Papers ----

def fetch_arxiv(since: str, max_results: int = 150) -> list[dict]:
    cats = " OR ".join(f"cat:{c}" for c in ARXIV_CATS)
    url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode({
        "search_query": cats, "sortBy": "submittedDate",
        "sortOrder": "descending", "max_results": max_results})
    out: list[dict] = []
    try:
        root = ET.fromstring(http_get(url))
        for e in root.findall(f"{ATOM}entry"):
            pub = (e.findtext(f"{ATOM}published") or "")[:10]
            if pub and pub < since:
                continue
            title = " ".join((e.findtext(f"{ATOM}title") or "").split())
            summary = " ".join((e.findtext(f"{ATOM}summary") or "").split())
            if not (ARXIV_KEYWORDS.search(title) or ARXIV_KEYWORDS.search(summary)):
                continue
            absurl = e.findtext(f"{ATOM}id") or ""
            aid = absurl.rsplit("/abs/", 1)[-1]
            out.append({
                "source": "arxiv", "id": f"arxiv:{aid.split('v')[0]}",
                "arxiv_id": aid, "title": title, "url": absurl,
                "summary": summary[:600], "published": pub,
            })
    except Exception as e:  # noqa: BLE001
        warn(f"arxiv failed: {e}")
    return out


def fetch_hf_papers(date: str) -> list[dict]:
    out: list[dict] = []
    try:
        url = f"https://huggingface.co/api/daily_papers?date={date}&limit=100"
        for it in http_json(url):
            p = it.get("paper") or {}
            aid = p.get("id") or it.get("id") or ""
            out.append({
                "source": "hf", "id": f"arxiv:{aid}", "arxiv_id": aid,
                "title": (p.get("title") or it.get("title") or "").strip(),
                "url": f"https://huggingface.co/papers/{aid}",
                "summary": (p.get("summary") or "").strip()[:600],
                "votes": p.get("upvotes") or it.get("upvotes") or 0, "published": date,
            })
    except Exception as e:  # noqa: BLE001
        warn(f"hf_papers {date} failed: {e}")
    return out


def fetch_hf_models(authors: list[str], since: str) -> list[dict]:
    """New model/checkpoint releases from trusted HF authors — catches drops like DSpark
    that ship as an HF model + an X post (not a GitHub release or an arXiv paper)."""
    out: list[dict] = []
    for a in authors:
        try:
            url = (f"https://huggingface.co/api/models?author={a}"
                   "&sort=createdAt&direction=-1&limit=30")
            for m in http_json(url):
                created = (m.get("createdAt") or "")[:10]
                if created and created < since:
                    continue
                mid = m.get("id") or m.get("modelId") or ""
                out.append({
                    "source": "hf_model", "id": f"hfmodel:{mid}", "repo": mid,
                    "title": mid, "url": f"https://huggingface.co/{mid}",
                    "likes": m.get("likes", 0), "downloads": m.get("downloads", 0),
                    "created": created,
                })
        except Exception as e:  # noqa: BLE001
            warn(f"hf_models {a} failed: {e}")
    return out


# ------------------------------------------------------------- Community ----

def fetch_hn(since: str) -> list[dict]:
    cutoff = int(datetime.strptime(since, "%Y-%m-%d")
                 .replace(tzinfo=timezone.utc).timestamp())
    seen: dict[str, dict] = {}
    for term in HN_TERMS:
        try:
            url = "https://hn.algolia.com/api/v1/search_by_date?" + urllib.parse.urlencode({
                "query": term, "tags": "story",
                "numericFilters": f"created_at_i>{cutoff}", "hitsPerPage": 20})
            for h in http_json(url).get("hits", []):
                oid = h.get("objectID")
                if not oid or oid in seen or (h.get("points") or 0) < 5:
                    continue
                seen[oid] = {
                    "source": "hn", "id": f"hn:{oid}", "title": (h.get("title") or "").strip(),
                    "url": h.get("url") or f"https://news.ycombinator.com/item?id={oid}",
                    "hn_url": f"https://news.ycombinator.com/item?id={oid}",
                    "points": h.get("points") or 0, "num_comments": h.get("num_comments") or 0,
                    "created_at": h.get("created_at"),
                }
        except Exception as e:  # noqa: BLE001
            warn(f"hn '{term}' failed: {e}")
    return sorted(seen.values(), key=lambda x: x["points"], reverse=True)


def fetch_reddit() -> list[dict]:
    out: list[dict] = []
    url = "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day"
    try:
        root = ET.fromstring(http_get(url, {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
            "Accept": "application/rss+xml, application/xml",
        }))
        for e in root.findall(f"{ATOM}entry"):
            link = e.find(f"{ATOM}link")
            href = link.get("href") if link is not None else ""
            out.append({"source": "reddit", "id": f"reddit:{href}",
                        "title": (e.findtext(f"{ATOM}title") or "").strip(), "url": href})
    except Exception as e:  # noqa: BLE001
        warn(f"reddit blocked/failed (ok, optional): {e}")
    return out


# ----------------------------------------------------------------- Blogs ----

def _rss_items(xml: bytes) -> list[dict]:
    items: list[dict] = []
    root = ET.fromstring(xml)
    for it in root.findall(".//item"):
        link = it.findtext("link") or ""
        items.append({
            "title": (it.findtext("title") or "").strip(), "url": link.strip(),
            "date": (it.findtext("pubDate") or "").strip(),
            "summary": re.sub("<[^>]+>", "", (it.findtext("description") or ""))[:400].strip(),
        })
    for e in root.findall(f"{ATOM}entry"):
        link = e.find(f"{ATOM}link")
        href = link.get("href") if link is not None else ""
        items.append({
            "title": (e.findtext(f"{ATOM}title") or "").strip(), "url": href,
            "date": (e.findtext(f"{ATOM}updated") or e.findtext(f"{ATOM}published") or "").strip(),
            "summary": re.sub("<[^>]+>", "", (e.findtext(f"{ATOM}summary") or ""))[:400].strip(),
        })
    return items


def fetch_blogs(limit_per_feed: int = 6) -> list[dict]:
    out: list[dict] = []
    for site, feed in BLOG_FEEDS:
        try:
            for it in _rss_items(http_get(feed))[:limit_per_feed]:
                if it["url"]:
                    out.append({"source": "blog", "site": site, "id": it["url"], **it})
        except Exception as e:  # noqa: BLE001
            warn(f"blog {site} ({feed}) failed: {e}")
    return out


# ------------------------------------------------------------------ main ----

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["daily", "range"], default="daily")
    ap.add_argument("--since", default=None)
    ap.add_argument("--config", default=CONFIG_PATH)
    ap.add_argument("--no-update-repos", action="store_true")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    since = parse_since(args.since) if args.since else (
        parse_since("400d") if args.mode == "range" else parse_since("2d"))
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    cfg = load_repos(args.config)
    do_update = args.mode == "daily" and not args.no_update_repos
    tracked_names = {t["repo"] for t in cfg["tracked"]}

    # --- org-watch BEFORE fetch so newly auto-tracked repos are included this run ---
    org_added: list[str] = []
    if do_update:
        try:
            org_added = org_watch(cfg, tracked_names)
            if org_added:
                warn(f"org-watch auto-tracked: {org_added}")
        except Exception as e:  # noqa: BLE001
            warn(f"org_watch skipped: {e}")

    tracked = cfg["tracked"]
    prs_repos = [t["repo"] for t in tracked if t.get("prs", True)]
    rel_repos = [t["repo"] for t in tracked if t.get("releases", True)]
    hf_authors = (cfg.get("discovery") or {}).get("hf_authors") or ["deepseek-ai"]

    result = {
        "meta": {"mode": args.mode, "since": since, "generated_for": today,
                 "tracked_repos": len(tracked)},
        "github_prs": fetch_github_prs(prs_repos, since, args.mode),
        "github_releases": fetch_github_releases(rel_repos, since),
        "papers_arxiv": fetch_arxiv(since),
        "papers_hf": fetch_hf_papers(today) if args.mode == "daily" else [],
        "hf_models": fetch_hf_models(hf_authors, since) if args.mode == "daily" else [],
        "hn": fetch_hn(since),
        "reddit": fetch_reddit() if args.mode == "daily" else [],
        "blogs": fetch_blogs(),
    }

    # --- mention-based promotion (daily only), gated by the curated awesome-list ---
    if do_update:
        try:
            awesome = load_awesome(cfg)
            blob = " ".join(
                str(x.get("title", "")) + " " + str(x.get("summary", "")) + " "
                + str(x.get("body_excerpt", "")) + " " + str(x.get("url", ""))
                for k, v in result.items() if isinstance(v, list) for x in v)
            promoted = tally_and_promote(cfg, blob, tracked_names, today, awesome)
            save_repos(args.config, cfg)
            result["meta"]["repo_update"] = {
                "org_added": org_added, "promoted": promoted,
                "awesome_size": len(awesome), "candidates": len(cfg.get("candidates", {}))}
            if promoted:
                warn(f"promoted to tracked: {promoted}")
        except Exception as e:  # noqa: BLE001
            warn(f"repo self-update skipped: {e}")

    counts = {k: len(v) for k, v in result.items() if isinstance(v, list)}
    warn(f"mode={args.mode} since={since} repos={len(prs_repos)}pr/{len(rel_repos)}rel counts={counts}")
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
