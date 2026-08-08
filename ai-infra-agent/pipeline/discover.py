#!/usr/bin/env python3
"""拓源（source discovery）for the daily-ai-infra agent.

agent.py fetch 负责「核心盘」——已知仓库的稳定监控。本模块（`agent.py discover`）负责另一条腿：
**主动往外探**，找你还不知道的项目 / 方向 / 术语，产出「🆕 新兴方向」栏的原料。

三招（都是确定性抓取，可脚本化；第四招 novelty 搜索需要判断力，留给 Claude 的 WebSearch）：

  1. trending    — GitHub Trending 日榜/周榜里 AI-infra 相关、且不在 tracked 里的仓
  2. awesome_new — 策展 awesome 列表相对上次快照的**新增条目**（别人整理的新方向，廉价高质）
  3. new_terms   — 今天抓到的文本里出现、但 sources.md「已知术语」里没有的词
                   （新术语 = 新方向的信号；需要 --from 传入 agent.py fetch 的 JSON）

外加 rising：GitHub search API 按 infra topic 找近期高星新仓（Trending 抓不到时的兜底）。

每一招独立容错：失败返回空 + warn，绝不中断整轮。输出归一化 JSON 到 stdout。

Usage:
    python3 ai-infra-agent/agent.py discover --from /tmp/ai-infra-20260807.json [--pretty]
    python3 ai-infra-agent/agent.py discover --from -            # 从 stdin 读 fetch_sources JSON
    python3 ai-infra-agent/agent.py discover --no-record         # 不更新快照（dry run）
"""

from __future__ import annotations

import argparse
import json
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

UA = "ai-infra-agent/0.3 (+https://github.com/personal-agents)"
CONFIG_PATH = paths.REPOS_JSON
SOURCES_PATH = paths.SOURCES_MD
STATE_PATH = paths.DISCOVER_STATE

# 与 agent.py fetch 保持一致的 infra 相关性闸门（挡掉 awesome 清单 / OCR / 应用层）
INFRA_KW = re.compile(
    r"infer|serv|kernel|gemm|attention|\bmla\b|\bmoe\b|expert|parallel|pipeline|"
    r"\bkv\b|cache|quant|spec|decod|prefill|throughput|latency|cuda|\bgpu\b|fp8|"
    r"nvlink|disagg|batch|radix|flash|tensor|\btrt\b|vllm|sglang|llm", re.I)

# `rising` 走 topic 搜索，topic 标签很松（ray / litgpt 都挂着 llm-serving），
# 所以用更严的闸门：必须命中**推理栈本身**的词，光有 "llm" 不算。
RISING_KW = re.compile(
    r"inferenc|serving|\bserve\b|decod|prefill|kv[\s-]?cache|quantiz|throughput|"
    r"latency|kernel|gemm|\battention\b|speculative|batching|vllm|sglang|tensorrt|"
    r"llama\.cpp|\bmoe\b|expert parallel|disaggregat", re.I)

# 教程 / 博客 / 面经 / 书 —— 高星但对情报毫无价值，直接挡掉
NOISE_KW = re.compile(
    r"tutorial|course|\bbook\b|cookbook|handbook|awesome|roadmap|interview|"
    r"\bnotes?\b|\bblog|study|cheat[\s-]?sheet|\bcurriculum|learning path|"
    r"教程|实战|面试|笔记|入门|指南|从零", re.I)

REPO_RE = re.compile(r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)")

# GitHub search：按 topic 找近期起势的 infra 仓（Trending 页改版时的兜底）
RISING_QUERIES = [
    "topic:llm-inference", "topic:llm-serving", "topic:inference-engine",
    "topic:kv-cache", "topic:llm-serving-framework",
]

# 术语候选：CamelCase（FlashAttention/PagedAttention）、全大写缩写（EPD/MTP）、
# 带数字的规格词（FP8/NVFP4/INT4/B200）
TERM_RES = [
    re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+\b"),   # CamelCase
    re.compile(r"\b[A-Z]{2,6}\d{0,2}\b"),                       # ALLCAPS / ALLCAPS+num
    re.compile(r"\b(?:FP|INT|NVFP|MX)\d+\b", re.I),             # 数值格式
]

# 通用技术词/噪声，永远不算「新术语」
TERM_STOP = {
    "API", "APIS", "HTTP", "HTTPS", "JSON", "YAML", "TOML", "HTML", "XML", "CSV",
    "PR", "PRS", "CI", "CD", "OK", "TODO", "FIXME", "WIP", "RFC", "README", "LICENSE",
    "URL", "URI", "UUID", "ID", "IDS", "CPU", "RAM", "SSD", "OS", "IO", "UI", "CLI",
    "SDK", "IDE", "VM", "VMS", "AWS", "GCP", "GPU", "GPUS", "NPU", "TPU", "AI", "ML",
    "LLM", "LLMS", "NLP", "RL", "SFT", "MIT", "BSD", "GPL", "V1", "V2", "V3", "V4",
    "TL", "DR", "FAQ", "QA", "PDF", "PNG", "JPG", "GIF", "USA", "EU", "UTC", "GMT",
    "AND", "OR", "NOT", "THE", "FOR", "WITH", "NEW", "ADD", "FIX", "USE", "ALL",
    "GitHub", "GitLab", "HuggingFace", "PyTorch", "TensorFlow", "JAX", "NumPy",
    "OpenAI", "DeepMind", "MacOS", "IOS", "JavaScript", "TypeScript", "PyPI",
    "README", "ArXiv", "OpenSource", "WebUI", "ChatGPT", "GPT", "BERT",
    # 硬件厂商 / 通用缩写：出现频率高但从来不是"新方向"
    "NVIDIA", "AMD", "ARM", "INTEL", "QUALCOMM", "APPLE", "META", "IBM", "DSL",
    "ABI", "ISA", "EULA", "ROI", "KPI", "SOTA", "BENCH", "EVAL", "DEMO", "BETA",
}


def warn(msg: str) -> None:
    print(f"[discover] {msg}", file=sys.stderr)


# HTTP 走共享层（带重试 + 退避），函数名保持不变，调用点无需改动
http_get = _http.get
http_json = _http.get_json


def gh_headers() -> dict:
    import os
    h = {"Accept": "application/vnd.github+json"}
    tok = os.environ.get("GITHUB_TOKEN")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def load_json(path: str, default):
    p = Path(path)
    if not p.is_file():
        return default
    try:
        return json.loads(p.read_text())
    except Exception as e:  # noqa: BLE001
        warn(f"{path} parse failed ({e}); using default")
        return default


# ------------------------------------------------------------ sources.md ----

def known_terms(path: str) -> set[str]:
    """解析 sources.md「## 已知术语」区 → 小写术语集合（判断"什么算新"的基线）。"""
    p = Path(path)
    if not p.is_file():
        warn(f"{path} not found — 首轮运行会把所有术语都当新的，属正常")
        return set()
    text = p.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"^##\s*已知术语.*?$(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    if not m:
        return set()
    body = m.group(1)
    body = re.sub(r"^>.*$", "", body, flags=re.M)          # 去掉引用行说明
    out = set()
    for tok in re.split(r"[,，\n]", body):
        tok = tok.strip().strip("`*-—·()（）")
        if not tok:
            continue
        low = tok.lower()
        out.add(low)
        # 多词术语（"CUDA graph" / "prefix cache"）也要按词入表，否则单独出现的
        # CUDA 会被当成"新术语"。同时收去掉标点的形态（TensorRT-LLM → tensorrtllm）。
        out.add(re.sub(r"[^a-z0-9]", "", low))
        for w in re.split(r"[\s\-_/.]+", low):
            if len(w) >= 3:
                out.add(w)
    out.discard("")
    return out


def known_repo_words(cfg: dict) -> set[str]:
    """tracked/ignore 里的仓名也算「已知」，避免把自己盯的仓当新术语。"""
    out: set[str] = set()
    for t in cfg.get("tracked") or []:
        name = t.get("repo", "")
        for part in re.split(r"[/_.-]", name):
            if part:
                out.add(part.lower())
    for name in cfg.get("ignore") or []:
        out.add(str(name).lower())
    return out


# -------------------------------------------------------------- trending ----

ARTICLE_RE = re.compile(r'<article class="Box-row">(.*?)</article>', re.S)
# 注意：GitHub 的 <a> 把 data-hydro-click 排在 href 前面，且仓名被 <span> 拆成两段
# （"owner /" + "repo"），所以只能从 href 取，且不能假设 href 紧跟 <a。
TREND_REPO_RE = re.compile(
    r'<h2[^>]*>.*?<a[^>]*\shref="/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"', re.S)
TREND_DESC_RE = re.compile(r'<p class="col-9[^"]*"[^>]*>(.*?)</p>', re.S)
TREND_STARS_RE = re.compile(r'([\d,]+)\s*stars? today', re.I)


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    s = (s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
          .replace("&quot;", '"').replace("&#39;", "'"))
    return " ".join(s.split())


def fetch_trending(tracked: set[str], ignore: set[str]) -> list[dict]:
    """GitHub Trending 日榜 + 周榜里的 AI-infra 相关新面孔。"""
    out: dict[str, dict] = {}
    for since in ("daily", "weekly"):
        try:
            html = http_get(f"https://github.com/trending?since={since}").decode(
                "utf-8", "ignore")
        except Exception as e:  # noqa: BLE001
            warn(f"trending {since} failed: {e}")
            continue
        for block in ARTICLE_RE.findall(html):
            m = TREND_REPO_RE.search(block)
            if not m:
                continue
            name = m.group(1)
            short = name.split("/")[-1].lower()
            if name in tracked or short in ignore or name in out:
                continue
            dm = TREND_DESC_RE.search(block)
            desc = _strip_html(dm.group(1)) if dm else ""
            blob = f"{name} {desc}"
            if not INFRA_KW.search(blob) or NOISE_KW.search(blob):
                continue
            sm = TREND_STARS_RE.search(_strip_html(block))
            out[name] = {
                "kind": "trending", "repo": name,
                "url": f"https://github.com/{name}", "desc": desc,
                "stars_today": sm.group(1) if sm else None, "board": since,
                "why": f"GitHub Trending {since} 榜，AI-infra 相关且不在 tracked 里",
            }
    return list(out.values())


def fetch_rising(tracked: set[str], ignore: set[str], days: int = 120) -> list[dict]:
    """GitHub search：近期 push 过的 infra topic 仓，按星排序（Trending 的兜底）。"""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    out: dict[str, dict] = {}
    for i, q in enumerate(RISING_QUERIES):
        if i:
            time.sleep(2)  # search API 未认证 10 req/min
        try:
            url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
                {"q": f"{q} pushed:>={cutoff} stars:>=150",
                 "sort": "stars", "order": "desc", "per_page": 15})
            for r in http_json(url, gh_headers()).get("items", []):
                name = r.get("full_name", "")
                short = name.split("/")[-1].lower()
                desc = r.get("description") or ""
                blob = f"{name} {desc}"
                if (not name or name in tracked or short in ignore or name in out
                        or short.startswith("awesome")
                        or NOISE_KW.search(blob)
                        or not RISING_KW.search(blob)):
                    continue
                out[name] = {
                    "kind": "rising", "repo": name,
                    "url": r.get("html_url"), "desc": r.get("description") or "",
                    "stars": r.get("stargazers_count", 0),
                    "pushed_at": (r.get("pushed_at") or "")[:10],
                    "why": f"GitHub topic 搜索命中 `{q}`，{r.get('stargazers_count', 0)} stars",
                }
        except Exception as e:  # noqa: BLE001
            warn(f"rising '{q}' failed: {e}")
    return sorted(out.values(), key=lambda x: x.get("stars", 0), reverse=True)[:20]


# ---------------------------------------------------------- awesome diff ----

def fetch_awesome_new(cfg: dict, state: dict, tracked: set[str], ignore: set[str],
                      record: bool) -> list[dict]:
    """策展 awesome 列表的**增量**：本次出现、上次快照里没有的条目。

    首轮只建快照、不报（否则会把整份清单当"新发现"倒出来）。"""
    lists = (cfg.get("discovery") or {}).get("awesome_lists") or []
    snaps: dict = state.setdefault("awesome_snapshots", {})
    out: list[dict] = []
    for lst in lists:
        md = None
        for branch in ("main", "master"):
            try:
                md = http_get(
                    f"https://raw.githubusercontent.com/{lst}/{branch}/README.md"
                ).decode("utf-8", "ignore")
                break
            except Exception as e:  # noqa: BLE001
                if branch == "master":
                    warn(f"awesome {lst} failed: {e}")
        if md is None:
            continue
        names = {m[:-4] if m.endswith(".git") else m for m in REPO_RE.findall(md)}
        names = {n for n in names if n.count("/") == 1}
        prev = set(snaps.get(lst, {}).get("repos") or [])
        first_run = not prev
        if not first_run:
            for name in sorted(names - prev):
                short = name.split("/")[-1].lower()
                if name in tracked or short in ignore or short.startswith("awesome"):
                    continue
                out.append({
                    "kind": "awesome_new", "repo": name,
                    "url": f"https://github.com/{name}", "desc": "",
                    "list": lst,
                    "why": f"策展清单 {lst} 新增条目（上次快照里没有）",
                })
        if record:
            snaps[lst] = {"repos": sorted(names),
                          "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
        if first_run:
            warn(f"awesome {lst}: 首轮建快照（{len(names)} 条），下次起只报增量")
    return out[:25]


# ------------------------------------------------------------- new terms ----

def extract_new_terms(payload: dict, known: set[str], limit: int = 25) -> list[dict]:
    """从今天抓到的标题/摘要里挑出「不在已知术语表」的词 —— 新方向的信号。

    只做粗筛（频次 + 停用词 + 已知表），最终判断交给 Claude：脚本给候选，模型定性质。"""
    docs: list[tuple[str, str]] = []   # (text, url)
    for key, val in (payload or {}).items():
        if not isinstance(val, list):
            continue
        for it in val:
            if not isinstance(it, dict):
                continue
            text = " ".join(str(it.get(f, "")) for f in
                            ("title", "name", "summary", "body_excerpt"))
            if text.strip():
                docs.append((text, it.get("url") or ""))

    counts: dict[str, int] = {}
    example: dict[str, str] = {}
    for text, url in docs:
        seen_here: set[str] = set()
        for rx in TERM_RES:
            for tok in rx.findall(text):
                low = tok.lower()
                if (tok in TERM_STOP or len(tok) < 3 or low in known
                        or re.sub(r"[^a-z0-9]", "", low) in known):
                    continue
                if tok.isdigit() or tok.lower() in seen_here:
                    continue
                seen_here.add(tok.lower())
                counts[tok] = counts.get(tok, 0) + 1
                example.setdefault(tok, url)

    # 合并大小写变体，只留出现 ≥2 次的（一次多半是噪声/拼写）
    merged: dict[str, dict] = {}
    for tok, c in counts.items():
        k = tok.lower()
        e = merged.setdefault(k, {"term": tok, "count": 0, "url": example.get(tok, "")})
        e["count"] += c
        if tok[:1].isupper() and not e["term"][:1].isupper():
            e["term"] = tok
    hits = [v for v in merged.values() if v["count"] >= 2]
    hits.sort(key=lambda x: x["count"], reverse=True)
    return hits[:limit]


# ------------------------------------------------------------------ main ----

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", default=None,
                    help="agent.py fetch 的 JSON 路径（'-' = stdin）；不给则跳过新术语识别")
    ap.add_argument("--config", default=CONFIG_PATH)
    ap.add_argument("--sources", default=SOURCES_PATH)
    ap.add_argument("--state", default=STATE_PATH)
    ap.add_argument("--no-record", action="store_true", help="不更新快照（dry run）")
    ap.add_argument("--pretty", action="store_true")
    args = ap.parse_args()

    cfg = load_json(args.config, {"tracked": [], "ignore": [], "discovery": {}})
    state = load_json(args.state, {})
    record = not args.no_record

    tracked = {t.get("repo") for t in (cfg.get("tracked") or [])}
    ignore = {str(x).lower() for x in (cfg.get("ignore") or [])}
    known = known_terms(args.sources) | known_repo_words(cfg)

    payload = None
    if args.src:
        try:
            payload = (json.load(sys.stdin) if args.src == "-"
                       else json.loads(Path(args.src).read_text()))
        except Exception as e:  # noqa: BLE001
            warn(f"--from {args.src} 读取失败: {e}（跳过新术语识别）")

    result = {
        "meta": {
            "generated_for": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "tracked_repos": len(tracked), "known_terms": len(known),
        },
        "trending": fetch_trending(tracked, ignore),
        "rising": fetch_rising(tracked, ignore),
        "awesome_new": fetch_awesome_new(cfg, state, tracked, ignore, record),
        "new_terms": extract_new_terms(payload, known) if payload else [],
    }

    if record:
        try:
            sp = Path(args.state)
            sp.parent.mkdir(parents=True, exist_ok=True)
            state["last_run"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            sp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        except Exception as e:  # noqa: BLE001
            warn(f"could not persist state: {e}")

    counts = {k: len(v) for k, v in result.items() if isinstance(v, list)}
    warn(f"known_terms={len(known)} counts={counts}")
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
