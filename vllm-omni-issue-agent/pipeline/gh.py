"""GitHub 只读查询：搜 issue、读 timeline、判断有没有人已经在做。

只读，不评论、不认领、不开 PR —— 往上游发东西是人的决定（上游的 AI Usage Policy
要求 PR 作者本人回答 intent gate、披露 AI 使用）。
"""
import datetime
import importlib.util
import os
import re
import urllib.parse

from . import paths


def _load_shared_http():
    spec = importlib.util.spec_from_file_location("_shared_http", paths.SHARED_HTTP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


http = _load_shared_http()

API = "https://api.github.com"

# 认领多久没下文就不算数了。实测有人留一句 "I'll take this" 之后几周没动静。
STALE_CLAIM_DAYS = 14

# 宁可误判成"有人在做"（少一个候选），也别漏判（跟别人撞车）。
# 撇号要认弯引号 ’：很多人的输入法 / 编辑器会把 I'd 打成 I’d，只认 ' 的话
# "I’d like to investigate this, can you assign this issue to me?" 这种明确认领会漏掉（#8614）。
CLAIM_RE = re.compile(r"""(?ix)
    \b(i['’]?ll|i\s+will|i['’]?d\s+like\s+to|i\s+can|i\s+could|let\s+me|i['’]?m\s+going\s+to
       |i\s+am\s+going\s+to|i\s+want\s+to)\s+
      (take|work\s+on|fix|look\s+into|handle|pick\s+(it\s+|this\s+)?up|submit|open|send
       |raise|create|investigate|help)\b
  | \b(can|could|may)\s+i\s+(take|work\s+on|pick|fix|try|help)\b
  | \bworking\s+on\s+(this|it|a\s+fix|the\s+fix)\b
  | \bassign\s+(this\s+|it\s+|the\s+)?(issue\s+)?to\s+me\b
  | (^|\s)/assign\b
  | \bi['’]?m\s+on\s+it\b
  | \bpr\s+(is\s+)?(coming|incoming|on\s+the\s+way|soon)\b
  | 我来 | 认领 | 我(来)?(修|处理|跟进|提\s*pr|提个\s*pr) | 我这边(修|处理|跟进|提)
""")

# 本地只有 H20（Hopper）。只标出确实复现不了的：非 NVIDIA 和 Blackwell 专属。
# 只做标记不做排除 —— 标着 [B200] 的 CI 失败有不少在 Hopper 上也能复现。
HW_RE = re.compile(r"(?i)\b(B200|B300|GB200|GB300|Blackwell|NPU|Ascend|910B\d?|XPU|Gaudi|HPU"
                   r"|ROCm|AMD|MI\d{3}X?|MUSA|Moore\s*Threads|Apple\s+Silicon|MPS|Jetson)\b")


def _headers(auth=True):
    h = {"Accept": "application/vnd.github+json"}
    tok = os.environ.get("GITHUB_TOKEN") if auth else None
    if tok:
        h["Authorization"] = "Bearer %s" % tok
    return h


def search_issues(upstream, query, since):
    q = "repo:%s %s created:>=%s" % (upstream, query, since)
    url = "%s/search/issues?%s" % (API, urllib.parse.urlencode(
        {"q": q, "sort": "created", "order": "desc", "per_page": 100}))
    return http.get_json(url, _headers(), label="search").get("items", [])


def issue(upstream, number):
    return http.get_json("%s/repos/%s/issues/%s" % (API, upstream, number), _headers(),
                         label="issue #%s" % number)


def timeline(upstream, number, max_pages=3):
    """故意不带 token：fine-grained token 没有 pull_requests 读权限（读别人的公开仓库也给不了），
    GitHub 会把"被某个 PR 提到"的 cross-referenced 事件静默过滤掉 —— 认领判断全靠它。
    实测 #8503 带 token 10 条、匿名 17 条，open 的 PR 全没了，有人在修的 issue 被当成未认领。
    代价是 timeline 吃未认证每小时 60 次的额度，超了会被标成未核查，不会读到残缺数据。"""
    events = []
    for page in range(1, max_pages + 1):
        url = "%s/repos/%s/issues/%s/timeline?per_page=100&page=%d" % (API, upstream, number, page)
        batch = http.get_json(url, _headers(auth=False), label="timeline #%s" % number)
        events.extend(batch)
        if len(batch) < 100:
            break
    return events


def _days_ago(stamp):
    try:
        when = datetime.datetime.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return None
    return (datetime.datetime.utcnow() - when).days


def _excerpt(text, match, width=80):
    start = max(match.start() - width, 0)
    snippet = text[start:match.end() + width]
    return " ".join(snippet.split())


def claims(upstream, events):
    """从 timeline 里挑出"有人在做"的证据：提到它的 PR、关联、口头认领。"""
    found = []
    for ev in events:
        kind = ev.get("event")
        if kind == "cross-referenced":
            src = (ev.get("source") or {}).get("issue") or {}
            pr = src.get("pull_request")
            if not pr:
                continue
            # 下游 fork / 别的项目的 PR 提到它，不代表上游有人在修
            same_repo = (src.get("repository") or {}).get("full_name") == upstream
            found.append({
                "kind": "pr" if same_repo else "xref",
                "state": "merged" if pr.get("merged_at") else src.get("state"),
                "ref": "#%s" % src.get("number") if same_repo else src.get("html_url"),
                "who": (src.get("user") or {}).get("login"),
                "title": src.get("title"),
                "url": src.get("html_url"),
                "at": ev.get("created_at"),
            })
        elif kind == "connected":
            found.append({"kind": "linked", "who": (ev.get("actor") or {}).get("login"),
                          "at": ev.get("created_at")})
        elif kind == "commented":
            user = ev.get("user") or ev.get("actor") or {}
            if user.get("type") == "Bot":
                continue
            body = ev.get("body") or ""
            m = CLAIM_RE.search(body)
            if not m:
                continue
            age = _days_ago(ev.get("created_at"))
            found.append({
                "kind": "comment",
                "who": user.get("login"),
                "at": ev.get("created_at"),
                "url": ev.get("html_url"),
                "excerpt": _excerpt(body, m),
                "stale": age is not None and age > STALE_CLAIM_DAYS,
            })
    return found


def status_of(found):
    """unclaimed / claimed / stale-claim / maybe-fixed。"""
    if any(c["kind"] == "pr" and c.get("state") == "open" for c in found):
        return "claimed"
    if any(c["kind"] == "linked" for c in found):
        return "claimed"
    talk = [c for c in found if c["kind"] == "comment"]
    if any(not c.get("stale") for c in talk):
        return "claimed"
    if any(c["kind"] == "pr" and c.get("state") == "merged" for c in found):
        return "maybe-fixed"
    if talk:
        return "stale-claim"
    return "unclaimed"


def hardware_hints(title, labels, body):
    text = " ".join([title or "", " ".join(labels), (body or "")[:3000]])
    return sorted({m.group(1).upper() for m in HW_RE.finditer(text)})
