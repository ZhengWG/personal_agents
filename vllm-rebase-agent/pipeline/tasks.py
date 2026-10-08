"""每日 rebase 的任务执行层 —— 只做机械动作，不做判断。

判断（这个冲突该怎么解）留给 Claude + 仓库里的 ant-release-rebase skill。
这里只负责：抓远端 → 隔离 worktree → 演练 merge/rebase → 把"哪里炸了"如实记下来。

一条设计原则：**一轮要把所有问题都找出来**。遇到冲突不停在第一个上，
记下来之后 `git rebase --skip` 继续往下走，这样一次就能看到全部冲突面，
而不是每天修一个、第二天才发现还有下一个。代价是被 skip 的 patch 不在结果树里，
后续 patch 可能出现连带冲突 —— 报告里明确标了 cascaded，别当成独立问题。
"""
import os

from . import gitutil as g
from . import release_audit
from . import verify
from .gitutil import GitError

MAX_REBASE_STEPS = 80
MAX_CONFLICT_FILES = 8
MAX_SAMPLE_LINES = 40


def _excerpts(wt, entries):
    """只有内容冲突（UU/AA）才有 <<<<<<< 片段可截；删除类冲突截了也是空的。"""
    picked = {}
    for entry in entries[:MAX_CONFLICT_FILES]:
        if "D" in entry["code"]:
            continue
        lines = g.conflict_excerpt(wt, entry["path"])
        if lines:
            picked[entry["path"]] = lines
    return picked


def _drive_rebase(wt, onto, upstream):
    """跑一趟 rebase，遇到停顿就记录并 skip，直到走完。

    两种停顿要分开看：
      - 有冲突文件 → 真冲突，需要人/Claude 按 playbook 解。
      - 没有冲突文件 → `--empty=stop` 拦下的空 patch。**这才是最危险的那种**：
        不加 --empty=stop 的话 git 会一声不吭地把它丢掉（SKILL.md 里 v0.25.0 的事故）。
    """
    found = {"conflicts": [], "empty": [], "error": None, "steps": 0}
    rc, text = g.git(
        ["rebase", "--onto", onto, upstream, "--empty=stop"], wt, check=False, timeout=3600
    )
    while rc != 0 and found["steps"] < MAX_REBASE_STEPS:
        marker = g.in_progress(wt)
        if marker is None:
            found["error"] = text[-2000:]
            return found
        found["steps"] += 1
        head = g.rebase_head(wt) or {"sha": "?", "subject": "(unknown)"}
        entries = g.conflict_entries(wt, "rebase")
        if entries:
            found["conflicts"].append(
                {
                    "commit": head,
                    "files": entries,
                    "cascaded": bool(found["conflicts"] or found["empty"]),
                    "excerpts": _excerpts(wt, entries),
                }
            )
        else:
            found["empty"].append(head)
        rc, text = g.git(["rebase", "--skip"], wt, check=False, timeout=3600)

    if rc != 0:
        found["error"] = "rebase 未能收敛（%d 步后仍在进行中）\n%s" % (
            found["steps"],
            text[-1000:],
        )
        g.abort_any(wt)
    return found


def _drive_merge(wt, onto):
    found = {"conflicts": [], "error": None, "ok": False}
    rc, text = g.git(["merge", "--no-edit", onto], wt, check=False, timeout=1800)
    found["ok"] = rc == 0
    if rc != 0:
        entries = g.conflict_entries(wt, "merge")
        if entries:
            found["conflicts"].append(
                {"commit": {"sha": "-", "subject": "merge %s" % onto},
                 "files": entries, "cascaded": False, "excerpts": _excerpts(wt, entries)}
            )
        else:
            found["error"] = text[-2000:]
        g.abort_any(wt)
    return found


def _alignment(wt, upstream, source, onto, head, pathspec=None):
    """diff-of-diffs：Ant delta 在新 base 上必须和在 main 上是同一份。

    对应 SKILL.md 第 4b 步。两侧 base 不同 → hunk 行号必然错位，所以比的是
    去掉行号后的 +/- 内容行。不一致的每一行都得能用"上游挪了代码"解释，
    否则就是丢了 patch 或多了东西。
    """
    # source 必须已经含有最新 main，否则 `diff main..source` 里除了 Ant delta
    # 还有"把 main 这几百个提交倒过来"的巨量反向改动，两边根本没法比
    # （实测 omni 上 tracker 合不动时退回裸 public_tracker，差异报到 53 万行）。
    if g.git(["merge-base", "--is-ancestor", upstream, source], wt, check=False)[0] != 0:
        return {"checked": False,
                "reason": "source 未包含最新 %s，diff-of-diffs 会混入上游反向改动，无意义" % upstream}
    try:
        left = g.normalized_diff(upstream, source, wt, pathspec)
        right = g.normalized_diff(onto, head, wt, pathspec)
    except GitError as exc:
        return {"checked": False, "error": str(exc)[:500]}

    only_left = [ln for ln in left if ln not in set(right)]
    only_right = [ln for ln in right if ln not in set(left)]
    return {
        "checked": True,
        "aligned": not only_left and not only_right,
        "source_lines": len(left),
        "result_lines": len(right),
        "only_in_source_count": len(only_left),
        "only_in_result_count": len(only_right),
        "only_in_source": only_left[:MAX_SAMPLE_LINES],
        "only_in_result": only_right[:MAX_SAMPLE_LINES],
    }


def _resolve(token, repo_cfg, ctx):
    """把 @main / @delta_source / @tracker_result / @latest_rc 展开成真 ref。"""
    table = {
        "@main": repo_cfg["community_main"],
        "@delta_source": repo_cfg["delta_source"],
        "@latest_rc": ctx.get("latest_rc"),
        "@tracker_result": ctx.get("task_heads", {}).get("tracker"),
    }
    if token in table:
        return table[token]
    return token


def run_task(task, repo_cfg, ctx, wt):
    upstream = repo_cfg["community_main"]
    onto_ref = _resolve(task["onto"], repo_cfg, ctx)
    source_ref = _resolve(task["source"], repo_cfg, ctx)
    used_fallback = False

    if not source_ref and task.get("source_fallback"):
        source_ref = _resolve(task["source_fallback"], repo_cfg, ctx)
        used_fallback = True

    entry = {
        "name": task["name"],
        "kind": task["kind"],
        "desc": task.get("desc", ""),
        "onto_ref": onto_ref,
        "source_ref": source_ref,
        "source_is_fallback": used_fallback,
        "status": "error",
        "head": None,
        "conflicts": [],
        "empty_dropped": [],
        "missing_patches": [],
        "expected_patches": [],
        "landed_patches": [],
        "alignment": {"checked": False},
        "push": {"done": False, "reason": "未启用"},
        "error": None,
    }

    if not onto_ref or not source_ref:
        entry["status"] = "skipped"
        entry["error"] = "上游任务没产出可用结果，且没有 fallback（onto=%r source=%r）" % (
            onto_ref,
            source_ref,
        )
        return entry

    try:
        entry["onto_sha"] = g.short(onto_ref, wt)
        entry["source_sha"] = g.short(source_ref, wt)
        g.reset_clean(wt, source_ref)

        if task["kind"] == "merge":
            found = _drive_merge(wt, onto_ref)
            found["empty"] = []
        else:
            entry["expected_patches"] = g.subjects("%s..%s" % (upstream, source_ref), wt)
            found = _drive_rebase(wt, onto_ref, upstream)

        entry["conflicts"] = found["conflicts"]
        entry["empty_dropped"] = found.get("empty", [])
        entry["error"] = found["error"]

        if found["error"]:
            entry["status"] = "error"
            return entry

        if g.in_progress(wt):
            g.abort_any(wt)
            entry["status"] = "error"
            entry["error"] = "跑完之后 worktree 仍停在中间状态，已 abort"
            return entry

        if task["kind"] == "merge" and not found.get("ok"):
            # merge 冲突时已经 --abort，HEAD 退回 source，不是产物。
            # 这时候去体检等于在检查"合并前的那棵树"，只会报一堆假问题。
            entry["status"] = "conflicts"
            return entry

        head = g.rev("HEAD", wt)
        entry["head"] = head[:10]

        if task["kind"] == "rebase":
            entry["landed_patches"] = g.subjects("%s..HEAD" % onto_ref, wt)
            landed = {p["subject"] for p in entry["landed_patches"]}
            entry["missing_patches"] = [
                p for p in entry["expected_patches"] if p["subject"] not in landed
            ]
            entry["alignment"] = _alignment(
                wt, upstream, source_ref, onto_ref, head, repo_cfg.get("align_pathspec")
            )

        resolved_files = sorted({
            f["path"] if isinstance(f, dict) else f
            for c in entry["conflicts"] for f in c["files"]
        })
        verify.verify(entry, wt, syntax_files=resolved_files)

        if entry["conflicts"]:
            entry["status"] = "conflicts"
        elif entry["empty_dropped"] or entry["missing_patches"]:
            entry["status"] = "dropped"
        elif entry["alignment"].get("checked") and not entry["alignment"].get("aligned"):
            entry["status"] = "drifted"
        else:
            entry["status"] = "clean"

    except GitError as exc:
        g.abort_any(wt)
        entry["status"] = "error"
        entry["error"] = str(exc)[:2000]
    except Exception as exc:                                  # noqa: BLE001
        g.abort_any(wt)
        entry["status"] = "error"
        entry["error"] = "%s: %s" % (type(exc).__name__, exc)

    return entry


def maybe_push(entry, task, repo_cfg, ctx, wt, push_enabled):
    """推送是唯一不可逆的一步，所以有三道闸：全局开关、任务开关、结果必须 clean。"""
    spec = task.get("push") or {}
    if not push_enabled:
        entry["push"] = {"done": False, "reason": "全局 push_enabled=false（只读试跑）"}
        return
    if not spec.get("enabled"):
        entry["push"] = {"done": False, "reason": "该任务 push.enabled=false"}
        return
    if entry["status"] != "clean":
        entry["push"] = {"done": False, "reason": "结果不是 clean（%s），拒绝推送" % entry["status"]}
        return
    if not entry.get("verified"):
        failed = [c["name"] for c in entry.get("checks", []) if not c["ok"]]
        entry["push"] = {"done": False, "reason": "验收未通过：%s" % ", ".join(failed)}
        return

    ref = spec["ref"].format(rc=ctx.get("latest_rc") or "")
    remote = repo_cfg["ant_remote"]
    args = ["push", remote]
    if spec.get("force"):
        tracking = "%s/%s" % (remote, ref)
        if g.ref_exists(tracking, wt):
            args.append("--force-with-lease=refs/heads/%s:%s" % (ref, g.rev(tracking, wt)))
        else:
            args.append("--force-with-lease")
    args.append("HEAD:refs/heads/%s" % ref)
    rc, text = g.git(args, wt, check=False, timeout=1800)
    entry["push"] = {
        "done": rc == 0,
        "ref": ref,
        "force": bool(spec.get("force")),
        "reason": "ok" if rc == 0 else text[-800:],
    }


def extract_playbook(repo_cfg, dest):
    """把仓库里的 ant-release-rebase skill 抠出来存本地，给 Claude 读。

    不能让 Claude 直接读 worktree：worktree 停在 detached 的演练结果上，
    skill 文件可能压根不在那个 commit 里。
    """
    os.makedirs(dest, exist_ok=True)
    saved = []
    for rel in repo_cfg.get("playbook_files", []):
        rc, body = g.git(
            ["show", "%s:%s" % (repo_cfg["playbook_ref"], rel)], repo_cfg["repo"], check=False
        )
        if rc != 0:
            continue
        target = os.path.join(dest, os.path.basename(rel))
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(body + "\n")
        saved.append(target)
    return saved


def run_repo(cfg, repo_cfg):
    result = {
        "name": repo_cfg["name"],
        "repo": repo_cfg["repo"],
        "fetch": {},
        "latest_rc": None,
        "tasks": [],
        "playbook": [],
        "error": None,
    }
    repo = repo_cfg["repo"]

    if not os.path.isdir(os.path.join(repo, ".git")):
        result["error"] = "不是 git 仓库：%s" % repo
        return result

    try:
        result["fetch"] = g.fetch(repo, [(repo_cfg["community_remote"], True),
                                         (repo_cfg["ant_remote"], False)])
        result["latest_rc"] = g.latest_release_tag(repo, repo_cfg["rc_tag_pattern"])
        result["main_sha"] = g.short(repo_cfg["community_main"], repo)
        result["delta_sha"] = g.short(repo_cfg["delta_source"], repo)
        result["ant_only_count"] = g.count(
            "%s..%s" % (repo_cfg["community_main"], repo_cfg["delta_source"]), repo
        )
        result["main_ahead"] = g.count(
            "%s..%s" % (repo_cfg["delta_source"], repo_cfg["community_main"]), repo, no_merges=False
        )
        result["main_subject"] = g.subject(repo_cfg["community_main"], repo)
        result["playbook"] = extract_playbook(repo_cfg, repo_cfg["playbook_dir"])
        result["release_audit"] = release_audit.audit(repo_cfg)
        g.ensure_worktree(repo, repo_cfg["worktree"], repo_cfg["community_main"])
    except GitError as exc:
        result["error"] = str(exc)[:2000]
        return result

    wt = repo_cfg["worktree"]
    ctx = {"latest_rc": result["latest_rc"], "task_heads": {}}

    for task in repo_cfg["tasks"]:
        entry = run_task(task, repo_cfg, ctx, wt)
        maybe_push(entry, task, repo_cfg, ctx, wt, cfg.get("push_enabled", False))
        if entry["status"] in ("clean", "dropped", "drifted") and entry["head"]:
            ctx["task_heads"][task["name"]] = entry["head"]
        result["tasks"].append(entry)

    g.abort_any(wt)
    result["task_heads"] = ctx["task_heads"]      # resolve 模式要用它挑重放基线
    return result
