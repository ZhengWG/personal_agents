"""把候选清单 + 分诊结论渲染成 Markdown。

报告分两半：**事实**（本文件生成，Claude 挂了也有）和**分析**（Claude 写在
ANALYSIS_MARKER 之后）。render 重写整个文件时要把分析原样留住。
"""
import os

from . import triage

ANALYSIS_MARKER = "<!-- claude-analysis -->"
ANALYSIS_PLACEHOLDER = "_（这一节由 Claude 按 vllm-omni-issue skill 填写；为空说明这一轮没跑到分诊步骤。）_"

STATUS_TEXT = {
    "unclaimed": "未认领",
    "stale-claim": "认领已过期",
    "claimed": "已有人在做",
    "maybe-fixed": "可能已修",
    "unchecked": "未核查",
}


def _cell(text):
    return (text or "").replace("|", "\\|").replace("\n", " ")


def _link(c):
    return "[#%d](%s)%s" % (c["number"], c["url"], " 🆕" if c.get("new") else "")


def _claim_text(claim):
    if claim["kind"] == "pr":
        return "PR %s（%s，@%s）" % (claim.get("ref"), claim.get("state"), claim.get("who"))
    if claim["kind"] == "xref":
        return "外部 PR %s（%s）" % (claim.get("ref"), claim.get("state"))
    if claim["kind"] == "linked":
        return "已关联 PR（@%s）" % claim.get("who")
    return "@%s %s：“%s”" % (claim.get("who"), (claim.get("at") or "")[:10],
                            claim.get("excerpt", "")[:120])


def summary_line(cands, tri=None):
    counts = cands.get("counts", {})
    head = "未认领 %d 个" % counts.get("unclaimed", 0)
    rest = ["%s %d" % (STATUS_TEXT[k], counts[k]) for k in
            ("stale-claim", "claimed", "maybe-fixed", "unchecked") if counts.get(k)]
    picks = [n for n, t in triage.ranked(tri or {}) if t["verdict"] == "fix"]
    if picks:
        head += "，推荐 " + " ".join("#%s" % n for n in picks[:3])
    return head + ("（%s）" % "，".join(rest) if rest else "")


def render(cands, tri, max_cards):
    items = cands.get("items", [])
    by_status = {}
    for c in items:
        by_status.setdefault(c["status"], []).append(c)
    by_number = {str(c["number"]): c for c in items}

    out = ["# vLLM-Omni 可认领 issue — %s" % cands["date"], ""]
    out.append("> `%s` 近 %d 天新开、无 assignee、无 closing 关联 PR 的 bug，共 %d 个。"
               % (cands["upstream"], cands["lookback_days"], len(items)))
    out.append("> %s。%s" % (summary_line(cands, tri), cands.get("http", "")))
    if cands.get("rate_limited"):
        out.append("> ⚠️ GitHub 限流，部分 issue 没读到 timeline：%s" % cands["rate_limited"])
    out.append("")

    if tri:
        out += ["## 分诊结论", "",
                "| # | 结论 | 卡 | 模型 | 工作量 | 理由 |",
                "|---|---|---|---|---|---|"]
        for num, t in triage.ranked(tri):
            c = by_number.get(num, {"number": int(num), "url": "", "title": ""})
            out.append("| %s | %s | %s | %s | %s | %s |" % (
                _link(c), triage.VERDICTS.get(t["verdict"], t["verdict"]),
                "" if t.get("cards") is None else t["cards"], _cell(t.get("model") or "—"),
                t.get("effort") or "", _cell(t.get("reason"))))
        fixes = [(n, t) for n, t in triage.ranked(tri) if t["verdict"] == "fix"]
        if fixes:
            out += ["", "动手修（本地分支，不推送；单次最多 %d 张卡）：" % max_cards, "", "```bash"]
            out += ["vllm-omni-issue-agent/run.sh --fix %s --cards %s" % (n, t["cards"])
                    for n, t in fixes]
            out.append("```")
        out.append("")

    def table(title, rows, with_claims=False):
        if not rows:
            return
        out.extend(["## %s（%d）" % (title, len(rows)), ""])
        if with_claims:
            out.extend(["| # | 依据 | 标题 |", "|---|---|---|"])
            for c in rows:
                why = "；".join(_claim_text(x) for x in c["claims"]) or c.get("check_error", "")
                out.append("| %s | %s | %s |" % (_link(c), _cell(why), _cell(c["title"])))
        else:
            out.extend(["| # | 开于 | 标签 | 硬件 | 💬 | 标题 |", "|---|---|---|---|---|---|"])
            for c in rows:
                labels = ", ".join(lb for lb in c["labels"] if lb != "bug")
                out.append("| %s | %s | %s | %s | %d | %s |" % (
                    _link(c), c["created"][5:], _cell(labels), ", ".join(c["hw"]),
                    c["comments"], _cell(c["title"])))
        out.append("")

    table("未认领", by_status.get("unclaimed", []))
    table("认领已过期（认领超过 14 天还没有 PR）", by_status.get("stale-claim", []), True)
    table("已有人在做", by_status.get("claimed", []), True)
    table("可能已修（有已合入的 PR 提到它，issue 还开着）", by_status.get("maybe-fixed", []), True)
    table("未核查（timeline 没读到）", by_status.get("unchecked", []))

    out += ["---", "", "## 分析", "", ANALYSIS_MARKER, "", ANALYSIS_PLACEHOLDER, ""]
    return "\n".join(out)


def keep_analysis(target, body):
    """重写报告时，Claude 已写的分析原样留住（vllm-rebase 10-09 到 10-13 天天被冲掉过）。"""
    if not os.path.exists(target):
        return body
    with open(target, encoding="utf-8") as fh:
        old = fh.read()
    _, sep, kept = old.partition(ANALYSIS_MARKER)
    kept = kept.strip()
    if not sep or not kept or kept == ANALYSIS_PLACEHOLDER:
        return body
    head, sep, _ = body.partition(ANALYSIS_MARKER)
    return "%s%s\n\n%s\n" % (head, sep, kept)


def issue_markdown(issue, events, found, status):
    """issue 正文 + 全部评论 + 认领判断，给 Claude 读的。issue 可以是 search 结果里的条目。"""
    lines = ["# #%d %s" % (issue["number"], issue["title"]), "",
             "- 链接：%s" % issue["html_url"],
             "- 作者：@%s，开于 %s，状态 %s" % ((issue.get("user") or {}).get("login"),
                                            issue["created_at"][:10], issue["state"]),
             "- 标签：%s" % ", ".join(lb["name"] for lb in issue.get("labels", [])),
             "- 认领判断：%s" % status, ""]
    for c in found:
        lines.append("  - %s" % {k: v for k, v in c.items() if k != "url"})
    lines += ["", "## 正文", "", issue.get("body") or "_（空）_", "", "## 评论", ""]
    for ev in events:
        if ev.get("event") == "commented":
            who = (ev.get("user") or ev.get("actor") or {}).get("login")
            lines += ["### @%s %s" % (who, (ev.get("created_at") or "")[:16]), "",
                      ev.get("body") or "", ""]
    return "\n".join(lines)
