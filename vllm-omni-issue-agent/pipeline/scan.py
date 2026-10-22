"""每日扫描：搜社区新开的 bug → 逐个读 timeline 判断有没有人在做 → 落 candidates.json。

只做机械筛选。能不能修、值不值得修、要几张卡，是 Claude 分诊时的判断。
"""
import datetime
import re
import sys
import time
import urllib.error

from . import gh, paths, report

_TEMPLATE_NOISE = re.compile(r"<!--.*?-->", re.S)


def _excerpt(body, limit=1200):
    text = _TEMPLATE_NOISE.sub("", body or "")
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def _rate_limited(exc):
    return isinstance(exc, urllib.error.HTTPError) and exc.code in (403, 429)


def run(cfg, read_timeline=True):
    scfg = cfg["scan"]
    upstream = cfg["upstream"]
    since = (datetime.date.today() - datetime.timedelta(days=scfg["lookback_days"])).isoformat()

    found = {}
    for i, query in enumerate(scfg["queries"]):
        if i:
            time.sleep(2)            # 未认证的 search API 每分钟 10 次
        for it in gh.search_issues(upstream, query, since):
            if "pull_request" in it:
                continue
            found.setdefault(it["number"], it)

    items = sorted(found.values(), key=lambda it: it["created_at"], reverse=True)
    items = items[:scfg["max_candidates"]]

    # "新"是和上一天比。同一天重扫要沿用当天的基线，否则第二遍全都不新了。
    prev = paths.load(paths.CANDIDATES)
    if prev.get("date") == paths.today():
        known = set(prev.get("known", []))
    else:
        known = {c["number"] for c in prev.get("items", [])}

    out = []
    checked = 0
    blocked = None
    for it in items:
        labels = [lb["name"] for lb in it.get("labels", [])]
        cand = {
            "number": it["number"],
            "title": it["title"].strip(),
            "url": it["html_url"],
            "author": (it.get("user") or {}).get("login"),
            "labels": labels,
            "created": it["created_at"][:10],
            "updated": it["updated_at"][:10],
            "comments": it.get("comments", 0),
            "hw": gh.hardware_hints(it["title"], labels, it.get("body")),
            "new": bool(known) and it["number"] not in known,
            "excerpt": _excerpt(it.get("body")),
            "claims": [],
            "checked": False,
        }
        if read_timeline and blocked is None and checked < scfg["max_timeline_checks"]:
            try:
                events = gh.timeline(upstream, it["number"])
                cand["claims"] = gh.claims(upstream, events)
                cand["checked"] = True
                checked += 1
                # search 结果里就有完整正文，连同刚读的评论一起落盘：分诊时直接读，
                # 不用再逐个调 API（未认证每小时只有 60 次，扫描已经用掉一半）
                paths.save_text(paths.issue_file(it["number"]), report.issue_markdown(
                    it, events, cand["claims"], gh.status_of(cand["claims"])))
            except Exception as exc:  # noqa: BLE001
                cand["check_error"] = "%s: %s" % (type(exc).__name__, exc)
                if _rate_limited(exc):
                    blocked = cand["check_error"]
                    print("[scan] GitHub 限流，后面的不再读 timeline：%s" % blocked, file=sys.stderr)
        cand["status"] = gh.status_of(cand["claims"]) if cand["checked"] else "unchecked"
        out.append(cand)

    counts = {}
    for cand in out:
        counts[cand["status"]] = counts.get(cand["status"], 0) + 1

    result = {
        "date": paths.today(),
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "upstream": upstream,
        "since": since,
        "lookback_days": scfg["lookback_days"],
        "counts": counts,
        "rate_limited": blocked,
        "http": gh.http.stats_line(),
        "known": sorted(known),
        "items": out,
    }
    paths.save(paths.CANDIDATES, result)
    return result
