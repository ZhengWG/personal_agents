"""把一轮演练的结构化结果渲染成人能看的 Markdown。

报告分两半：**事实**（本文件生成，纯机械，claude 挂了也有）和
**分析**（Claude 按 ant-release-rebase skill 追加到末尾的占位区）。
分开的理由：事实部分必须每天都在，判断部分允许缺失。
"""
import re

STATUS_ICON = {
    "clean": "✅",
    "conflicts": "⚠️",
    "dropped": "🔴",
    "drifted": "🟠",
    "error": "💥",
    "skipped": "⏭️",
}

STATUS_TEXT = {
    "clean": "干净",
    "conflicts": "有冲突",
    "dropped": "掉 patch",
    "drifted": "delta 漂移",
    "error": "执行失败",
    "skipped": "跳过",
}

ANALYSIS_MARKER = "<!-- claude-analysis -->"
ANALYSIS_PLACEHOLDER = "_（这一节由 Claude 按 ant-release-rebase skill 填写；为空说明这一轮没跑到分析步骤。）_"


def _badge(status):
    return "%s %s" % (STATUS_ICON.get(status, "❔"), STATUS_TEXT.get(status, status))


def severity(run):
    """整轮最严重的状态 —— 决定通知语气。"""
    order = ["clean", "skipped", "drifted", "conflicts", "dropped", "error"]
    worst = "clean"
    for repo in run.get("repos", []):
        if repo.get("error"):
            worst = "error"
        for task in repo.get("tasks", []):
            if order.index(task["status"]) > order.index(worst):
                worst = task["status"]
    return worst


def promotable(run):
    """社区已出正式版、且当天 release 产物够格固化的仓库。

    判断「什么时候可以打正式 release」这件事能自动化，但「要不要打」不能：
    正式分支 ant/releases/vX.Y.Z 是 non-force 的对外发布，推出去就在那儿了，
    而要不要跟着社区发版有一半是产品决定。所以这里只负责把判断结果和现成命令
    摆出来，推送留给人 —— 和 tracker 的 after_resolve=false 是同一个道理。
    """
    out = []
    for repo in run.get("repos", []):
        rc = repo.get("latest_rc") or ""
        # 带 rcN 后缀的是预发布，社区自己都还没定版，不提示
        if not rc or re.search(r"rc\d+$", rc):
            continue
        for task in repo.get("tasks", []):
            if task.get("name") != "release":
                continue
            sess = (task.get("resolve") or {})
            push = task.get("push") or {}
            # 够格 = 本轮验收过、没有低自信、而且确实推出去了 -daily
            if task.get("verified") and push.get("done"):
                out.append({
                    "repo": repo.get("name"),
                    "tag": rc,
                    "head": push.get("head") or task.get("head"),
                    "daily_ref": push.get("ref"),
                })
    return out


def push_failures(run):
    """真跑了 git push 但没成功的任务 —— 被闸门挡下的不算。

    区别在于 push 记录里有没有 ref：闸门拒绝时只写 reason（"有 1 处低自信解法"
    之类），真推过才会带上 ref 和 head。这个要单独报，因为 severity() 只看
    task status，推送失败不会改变它 —— 开了 push_enabled 之后如果不报，
    force-with-lease 被挡、网络抖、权限不足都会静默，过几天才发现分支没动。
    """
    out = []
    for repo in run.get("repos", []):
        for task in repo.get("tasks", []):
            push = task.get("push") or {}
            if push.get("ref") and not push.get("done"):
                out.append("%s/%s → %s" % (repo.get("name"), task.get("name"), push["ref"]))
    return out


def mirror_failures(run):
    """OSS 镜像同步真失败的仓库 —— 按配置忽略的（上游还没发布的 wheel）不算。

    和 push_failures 一样要单独报：severity() 只看 task status，同步失败不会
    改变它。而这正是 2026-10-19 那次事故的根因之一 —— 镜像缺包只在内网 CI 里
    报错，本地这边一声不响，挂了三天才被发现。
    """
    out = []
    for repo in run.get("repos", []):
        m = repo.get("oss_mirror") or {}
        if m and not m.get("done"):
            out.append("%s(%s)" % (repo.get("name"), m.get("reason", "")[:40]))
    return out


def summary_line(run):
    bits = []
    for repo in run.get("repos", []):
        if repo.get("error"):
            bits.append("%s: 执行失败" % repo["name"])
            continue
        parts = []
        for task in repo.get("tasks", []):
            parts.append("%s=%s" % (task["name"], STATUS_TEXT.get(task["status"], task["status"])))
        bits.append("%s: %s" % (repo["name"], " ".join(parts)))
    line = " | ".join(bits) or "没有任何仓库被处理"
    failed = push_failures(run)
    if failed:
        line += " ‖ 推送失败 %d 个：%s" % (len(failed), "、".join(failed))
    mir = mirror_failures(run)
    if mir:
        line += " ‖ OSS 镜像同步失败：%s" % "、".join(mir)
    prom = promotable(run)
    if prom:
        line += " ‖ 可固化正式 release：%s" % "、".join(
            "%s→%s" % (x["repo"], x["tag"]) for x in prom)
    return line


def _task_block(out, repo, task):
    out.append("#### `%s` — %s" % (task["name"], _badge(task["status"])))
    out.append("")
    out.append("%s" % task.get("desc", ""))
    out.append("")
    out.append("| | |")
    out.append("|---|---|")
    out.append("| 方式 | `%s` |" % task["kind"])
    out.append("| onto | `%s` (`%s`) |" % (task["onto_ref"], task.get("onto_sha", "?")))
    src = "`%s` (`%s`)" % (task["source_ref"], task.get("source_sha", "?"))
    if task.get("source_is_fallback"):
        src += " —— ⚠️ 上游任务没产出，回退用的"
    out.append("| source | %s |" % src)
    if task.get("head"):
        out.append("| 结果 HEAD | `%s` |" % task["head"])
    out.append("| 推送 | %s |" % ("已推送 `%s`" % task["push"].get("ref")
                                   if task["push"].get("done")
                                   else "未推送 —— %s" % task["push"].get("reason")))
    out.append("")

    checks = task.get("checks") or []
    if checks:
        bad = [c for c in checks if not c["ok"]]
        out.append("**体检**：%d/%d 通过%s" % (
            len(checks) - len(bad), len(checks),
            "" if not bad else " —— 未过：" + "、".join(c["name"] for c in bad)))
        out.append("")
        for c in bad:
            if c.get("detail"):
                out.append("- `%s`：%s" % (c["name"], c["detail"]))
        if any(c.get("detail") for c in bad):
            out.append("")

    if task.get("error"):
        out.append("```text")
        out.append(task["error"])
        out.append("```")
        out.append("")

    if task.get("empty_dropped"):
        out.append("**🔴 被 `--empty=stop` 拦下的空 patch（不拦就会被 git 静默丢掉）**")
        out.append("")
        for c in task["empty_dropped"]:
            out.append("- `%s` %s" % (c["sha"], c["subject"]))
        out.append("")
        out.append("> 含义：这个 patch 的落点（方法/文件）在新 base 上已经不存在或已被上游吸收。")
        out.append("> 需要人工判断是「上游已经做了，可以不要」还是「落点挪了，要换地方重新贴」。")
        out.append("")

    if task.get("missing_patches"):
        out.append("**🔴 期望回放但没落地的 commit**")
        out.append("")
        for c in task["missing_patches"]:
            out.append("- `%s` %s" % (c["sha"], c["subject"]))
        out.append("")

    for idx, conflict in enumerate(task.get("conflicts", []), 1):
        tag = "（连带冲突，前面已 skip 过 patch）" if conflict.get("cascaded") else ""
        out.append("**⚠️ 冲突 %d：`%s` %s** %s" % (
            idx, conflict["commit"]["sha"], conflict["commit"]["subject"], tag))
        out.append("")
        for entry in conflict["files"]:
            if isinstance(entry, dict):
                out.append("- `%s` — %s (`%s`)" % (entry["path"], entry["kind"], entry["code"]))
            else:
                out.append("- `%s`" % entry)
        out.append("")
        for path, lines in conflict.get("excerpts", {}).items():
            out.append("<details><summary>%s 冲突片段</summary>" % path)
            out.append("")
            out.append("```text")
            out.extend(lines)
            out.append("```")
            out.append("")
            out.append("</details>")
            out.append("")

    align = task.get("alignment") or {}
    if align.get("checked"):
        if align.get("aligned"):
            out.append("**✅ delta 对齐**：%d 行改动两侧完全一致。" % align.get("source_lines", 0))
        else:
            out.append("**🟠 delta 不对齐**：source 侧 %d 行 / 结果侧 %d 行，"
                       "只在 source 出现 %d 行，只在结果出现 %d 行。" % (
                           align.get("source_lines", 0), align.get("result_lines", 0),
                           align.get("only_in_source_count", 0),
                           align.get("only_in_result_count", 0)))
            out.append("")
            out.append("> 每一行差异都必须能用「上游挪了代码/改了上下文」解释。")
            out.append("> 只要有一行是 Ant 的**业务逻辑**只在一侧出现，就是丢了 patch 或多了东西。")
            out.append("")
            if align.get("only_in_source"):
                out.append("<details><summary>只在 %s..%s 出现（可能是丢了）</summary>" % (
                    "main", task["source_ref"]))
                out.append("")
                out.append("```diff")
                out.extend(align["only_in_source"])
                out.append("```")
                out.append("")
                out.append("</details>")
                out.append("")
            if align.get("only_in_result"):
                out.append("<details><summary>只在演练结果出现（可能是多了）</summary>")
                out.append("")
                out.append("```diff")
                out.extend(align["only_in_result"])
                out.append("```")
                out.append("")
                out.append("</details>")
                out.append("")
    out.append("")


BASIS_TEXT = {
    "trivial": "空白漂移",
    "playbook": "playbook 已有结论",
    "new": "新判断",
    "reanchor": "重新定位落点",
}

# 风险从高到低。人的注意力有限，报告按这个顺序排 —— 先看最可能出错的那几个，
# 而不是按 git 碰上它们的先后。
RISK_ORDER = ["reanchor", "new", "playbook", "trivial"]


def _resolve_section(out, sessions):
    if not sessions:
        return
    out.append("## 自动解冲突")
    out.append("")
    out.append("| 仓库/任务 | 结果 | 已解 | 退役 | 待人工 | 候选分支 | delta 对齐 |")
    out.append("|---|---|---:|---:|---:|---|---|")
    for key, sess in sorted(sessions.items()):
        entry = sess.get("entry") or {}
        align = entry.get("alignment") or {}
        if not align.get("checked"):
            acell = "—"
        elif align.get("aligned"):
            acell = "✅ %d 行全同" % align.get("source_lines", 0)
        else:
            acell = "🟠 差 %d/%d" % (align.get("only_in_source_count", 0),
                                     align.get("only_in_result_count", 0))
        state = {"finished": "✅ 跑完", "handoff": "⏸️ 交人工",
                 "aborted": "⏹️ 放弃", "error": "💥 失败"}.get(
                     sess.get("state"), sess.get("state", "?"))
        if sess.get("entry") and not entry.get("verified"):
            state = "⚠️ 跑完但体检未过"
        out.append("| `%s` | %s | %d | %d | %d | %s | %s |" % (
            key, state, len(sess.get("resolutions", [])), len(sess.get("drops", [])),
            len(sess.get("handoffs", [])),
            "`%s`" % sess["candidate"] if sess.get("candidate") else "—", acell))
    out.append("")
    out.append("> 候选分支**没有推送**，只在本地。`git log <候选分支>` / "
               "`git diff <tag>..<候选分支>` 可以直接检视。")
    out.append("")

    for key, sess in sorted(sessions.items()):
        res = sess.get("resolutions", [])
        drops = sess.get("drops", [])
        hand = sess.get("handoffs", [])
        if not (res or drops or hand):
            continue
        out.append("### %s" % key)
        out.append("")
        out.append("基线：`%s` ← `%s`（%s）" % (
            sess.get("onto_ref", "?"), sess.get("source_ref", "?"), sess.get("source_why", "")))
        out.append("")
        if hand:
            out.append("**⏸️ 待人工**")
            out.append("")
            for h in hand:
                out.append("- `%s` %s —— %s" % (
                    h["commit"]["sha"], h["commit"]["subject"], h["reason"]))
            out.append("")
        if drops:
            out.append("**🗑️ 确认退役（上游已吸收）**")
            out.append("")
            for d in drops:
                out.append("- `%s` %s" % (d["commit"]["sha"], d["commit"]["subject"]))
                out.append("  - 依据：%s" % d["reason"])
            out.append("")
        if res:
            ordered = sorted(res, key=lambda r: (
                RISK_ORDER.index(r["basis"]) if r["basis"] in RISK_ORDER else 9,
                0 if r["confidence"] == "low" else 1))
            out.append("**已解（按风险从高到低）**")
            out.append("")
            for r in ordered:
                flag = "🔴 低自信" if r["confidence"] == "low" else ""
                out.append("- **%s** %s `%s` %s %s" % (
                    BASIS_TEXT.get(r["basis"], r["basis"]),
                    "·", r["commit"]["sha"], r["commit"]["subject"], flag))
                for f in r["files"]:
                    out.append("  - `%s` (%s)" % (f["path"], f["code"]))
                out.append("  - 依据：%s" % r["note"])
            out.append("")


def render(run):
    out = []
    out.append("# vLLM 每日 rebase 演练 — %s" % run["date"])
    out.append("")
    mode = "只读演练（不推送）" if not run.get("push_enabled") else "演练并推送"
    out.append("模式：**%s** · 开始 %s · 耗时 %ds" % (
        mode, run.get("started", "?"), int(run.get("elapsed", 0))))
    out.append("")

    out.append("## 总览")
    out.append("")
    out.append("| 仓库 | 任务 | 结果 | 冲突 | 掉 patch | delta 对齐 |")
    out.append("|---|---|---|---:|---:|---|")
    for repo in run.get("repos", []):
        if repo.get("error"):
            out.append("| `%s` | — | 💥 执行失败 | | | |" % repo["name"])
            continue
        for task in repo.get("tasks", []):
            align = task.get("alignment") or {}
            if not align.get("checked"):
                acell = "—"
            elif align.get("aligned"):
                acell = "✅"
            else:
                acell = "🟠 差 %d/%d 行" % (align.get("only_in_source_count", 0),
                                            align.get("only_in_result_count", 0))
            out.append("| `%s` | `%s` | %s | %d | %d | %s |" % (
                repo["name"], task["name"], _badge(task["status"]),
                len(task.get("conflicts", [])),
                len(task.get("empty_dropped", [])) + len(task.get("missing_patches", [])),
                acell))
    out.append("")
    out.append("> 一次跑到底：遇到冲突不停，记下来后 `git rebase --skip` 继续，"
               "所以**一轮能看到全部冲突面**。被 skip 的 patch 不在结果树里，"
               "标了「连带冲突」的条目可能只是前面 skip 的副作用。")
    out.append("")

    for repo in run.get("repos", []):
        out.append("## %s" % repo["name"])
        out.append("")
        if repo.get("error"):
            out.append("```text")
            out.append(repo["error"])
            out.append("```")
            out.append("")
            continue
        out.append("- 路径：`%s`" % repo["repo"])
        out.append("- 社区 main：`%s`" % repo.get("main_sha", "?"))
        out.append("- Ant delta 源：`%s`，Ant-only commit **%s** 个" % (
            repo.get("delta_sha", "?"), repo.get("ant_only_count", "?")))
        out.append("- 最新 release tag：`%s`；社区 main 领先 delta %s 个提交" % (repo.get("latest_rc") or "（没找到）", repo.get("main_ahead", "?")))
        audit = repo.get("release_audit") or {}
        if audit.get("release_only"):
            out.append("- 🔴 **release 独有提交 %d 个**：在 `%s` 上、但不在 delta 来源里，"
                       "下一版 release 会静默丢掉它们，需要回灌：" % (len(audit["release_only"]), audit["branch"]))
            for c in audit["release_only"]:
                out.append("    - `%s` %s（%s）" % (c["sha"], c["subject"], c["why"]))
        elif audit.get("branch"):
            out.append("- ✅ release 独有提交：无（对照 `%s`；上游 backport %d 个已自带）"
                       % (audit["branch"], len(audit.get("backports", []))))
        if audit.get("skipped_empty"):
            out.append("- ⚠️ 只有分支、没有 Ant 提交的 release 空壳：%s"
                       % "、".join("`%s`" % b for b in audit["skipped_empty"]))
        failed = [name for name, info in (repo.get("fetch") or {}).items() if not info.get("ok")]
        if failed:
            out.append("- ⚠️ fetch 失败的远端：%s —— **基线可能是旧的，下面的结论都要打折**"
                       % ", ".join(failed))
        out.append("")
        for task in repo.get("tasks", []):
            _task_block(out, repo, task)

    _resolve_section(out, run.get("resolve") or {})

    prom = promotable(run)
    if prom:
        out.append("## 可固化为正式 release")
        out.append("")
        out.append("社区已发布正式版，且本轮 release 产物验收通过、已推演练分支。"
                   "固化是对外发布，所以不自动做 —— 确认后执行：")
        out.append("")
        for x in prom:
            out.append("```bash")
            out.append("# %s：社区 %s 已正式发布" % (x["repo"], x["tag"]))
            out.append("cd <%s 的 checkout>" % x["repo"])
            out.append("git push ant %s:refs/heads/ant/releases/%s" % (
                x["head"] or x["daily_ref"], x["tag"].lstrip("v") and x["tag"]))
            out.append("```")
        out.append("")

    out.append("## 分析与建议")
    out.append("")
    out.append(ANALYSIS_MARKER)
    out.append("")
    out.append(ANALYSIS_PLACEHOLDER)
    out.append("")
    return "\n".join(out)
