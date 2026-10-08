"""逐个解冲突的会话引擎 —— 给 Claude 用的"一步一停"接口。

和 tasks.py 的 radar 模式是**两回事，不互相替代**：
  radar   （tasks.py）遇到冲突就记下来 `--skip` 往下走，图的是一轮看全冲突面；
  resolve （本文件）  一次停一个冲突，等 Claude 解完再走，图的是产出一棵**完整**的候选树。

为什么非要有完整的树：delta 对齐（diff-of-diffs）只有在 rebase 真正跑完时才有意义。
radar 模式下报出来的差异永远被"我主动 skip 掉的那些 patch"占满 —— 实测 vllm-ant
报「差 11 行」，那 11 行恰好就是被 skip 的那个 patch，等于什么也没验证。

## 三条写死在代码里的规矩（不是写在 prompt 里指望模型守）

1. **没有 skip 这个动作**。解不动只能 `stop`（标记待人工），不能"跳过继续"。
   `git rebase --skip` 正是 patch 静默消失的那条路径。
2. **continue 前必检查冲突标记**。文件里还留着 `<<<<<<<` 就直接拒绝，不给 add。
3. **空 commit 必须显式确认**。解完发现和 HEAD 没差别 → 这个 patch 要消失了，
   必须走 `drop` 并给出理由（上游已吸收的依据），理由会进报告。
"""
import datetime
import json
import os

from . import gitutil as g
from . import paths
from . import tasks
from . import verify
from .gitutil import GitError

SESSION_FILE = os.path.join(paths.STATE_DIR, "resolve.json")

BASIS = ("playbook", "new", "reanchor", "trivial")
CONFIDENCE = ("high", "low")


def _load():
    try:
        with open(SESSION_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"current": None, "sessions": {}}


def _save(state):
    os.makedirs(paths.STATE_DIR, exist_ok=True)
    tmp = SESSION_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, SESSION_FILE)


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _find(cfg, repo_name, task_name):
    for repo_cfg in cfg["repos"]:
        if repo_cfg["name"] != repo_name:
            continue
        for task in repo_cfg["tasks"]:
            if task["name"] == task_name:
                return repo_cfg, task
        raise GitError("仓库 %s 没有任务 %s" % (repo_name, task_name))
    raise GitError("配置里没有仓库 %s" % repo_name)


def candidate_branch(repo_name, task_name):
    return "rebase-agent/%s-candidate" % task_name


def _fresh_session(repo_name, task_name):
    """那个候选分支是不是今天跑出来的。"""
    sess = _load().get("sessions", {}).get("%s/%s" % (repo_name, task_name))
    if not sess or sess.get("state") != "finished":
        return False
    stamp = sess.get("finished") or ""
    return stamp.startswith(datetime.date.today().isoformat())


def _pick_source(repo_cfg, task, wt, explicit=None):
    """决定这一轮在什么树上重放，并说清楚为什么是它。

    优先用依赖任务**解完冲突之后**的候选分支：tracker 解好了，daily 就该在
    合过 main 的树上重放，而不是退回那棵落后几百个提交的裸 public_tracker
    （在那上面 diff-of-diffs 会混入上游反向改动，实测报到 53 万行）。
    """
    if explicit:
        return explicit, "命令行指定"

    token = task.get("source")
    if token == "@tracker_result":
        cand = candidate_branch(repo_cfg["name"], "tracker")
        # 候选分支是持久 ref，跨天还在。只有**今天这一轮**解出来的才能当基线 ——
        # 拿昨天的候选当今天的重放基线，会产出一份看起来全绿、其实基线过期的报告，
        # 比报错危险得多。
        if g.ref_exists(cand, wt) and _fresh_session(repo_cfg["name"], "tracker"):
            return cand, "tracker 的候选分支，本轮已解完冲突"
        run = paths.load_state()
        for repo in run.get("repos", []):
            if repo["name"] == repo_cfg["name"]:
                head = (repo.get("task_heads") or {}).get("tracker")
                if head:
                    return head, "radar 那轮 tracker 的产物"
        fallback = task.get("source_fallback", "@delta_source")
        ref = repo_cfg["delta_source"] if fallback == "@delta_source" else fallback
        return ref, "⚠️ tracker 没有可用产物，退回裸 delta（对齐检查会失效）"

    if token == "@delta_source":
        return repo_cfg["delta_source"], "配置指定"
    return token, "配置指定"


def _onto(repo_cfg, task, wt):
    token = task["onto"]
    if token == "@main":
        return repo_cfg["community_main"]
    if token == "@latest_rc":
        return g.latest_release_tag(repo_cfg["repo"], repo_cfg["rc_tag_pattern"])
    return token


def _conflict_view(wt, sess):
    """当前停在哪儿、要解什么 —— Claude 每一步读的就是这个。"""
    kind = sess["kind"]
    entries = g.conflict_entries(wt, "merge" if kind == "merge" else "rebase")
    head = g.rebase_head(wt) if kind == "rebase" else None
    view = {
        "state": "conflict" if entries else "empty",
        "repo": sess["repo"],
        "task": sess["task"],
        "worktree": wt,
        "commit": head or {"sha": "-", "subject": "merge %s" % sess["onto_ref"]},
        "files": entries,
        "progress": sess.get("progress", ""),
        "resolved_so_far": len(sess["resolutions"]),
    }
    if entries:
        view["excerpts"] = {
            e["path"]: g.conflict_excerpt(wt, e["path"], max_lines=120)
            for e in entries[:6] if "D" not in e["code"]
        }
    return view


def _progress(wt):
    gitdir = g.out(["rev-parse", "--absolute-git-dir"], wt)
    base = os.path.join(gitdir, "rebase-merge")
    try:
        with open(os.path.join(base, "msgnum"), encoding="utf-8") as fh:
            cur = fh.read().strip()
        with open(os.path.join(base, "end"), encoding="utf-8") as fh:
            end = fh.read().strip()
        return "%s/%s" % (cur, end)
    except OSError:
        return ""


def _settle(sess, wt, rc, text):
    """rebase/merge 跑了一步之后，看落在什么状态上。"""
    sess["last_output"] = text[-3000:]
    if rc == 0 and not g.in_progress(wt):
        sess["state"] = "done"
        sess["head"] = g.rev("HEAD", wt)[:10]
        return {"state": "done", "head": sess["head"],
                "resolved": len(sess["resolutions"]),
                "next": "跑 `agent.py resolve finish` 做体检并落候选分支"}
    if not g.in_progress(wt):
        sess["state"] = "error"
        return {"state": "error", "detail": text[-2000:]}
    sess["progress"] = _progress(wt)
    sess["state"] = "conflict"
    return _conflict_view(wt, sess)


def _owner_alive(state):
    pid = state.get("owner_pid")
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def start(cfg, repo_name, task_name, source=None, force=False, onto=None):
    repo_cfg, task = _find(cfg, repo_name, task_name)

    # 锁：两个进程同时对一棵 worktree 做 reset --hard 会互相冲掉进度（09-23 真撞上过：
    # 手工 resolve 和 launchd 那轮同时跑，状态文件被覆盖）。持锁进程还活着就拒绝。
    # 锁的主人是调用 agent.py 的父进程链上的长寿进程 —— 用 PPID（Claude/shell），
    # 因为每次 `agent.py resolve ...` 都是一个新的短命 python 进程。
    prev = _load()
    busy = prev.get("current")
    if busy and not force and _owner_alive(prev) and prev.get("owner_pid") != os.getppid():
        raise GitError("会话 %s 正被进程 %s 占用，拒绝开新会话（确认对方已死可加 --force）"
                       % (busy, prev.get("owner_pid")))
    wt = repo_cfg["worktree"]
    g.ensure_worktree(repo_cfg["repo"], wt, repo_cfg["community_main"])

    onto_ref = onto or _onto(repo_cfg, task, wt)
    source_ref, why = _pick_source(repo_cfg, task, wt, source)
    g.reset_clean(wt, source_ref)

    sess = {
        "repo": repo_name,
        "task": task_name,
        "kind": task["kind"],
        "onto_ref": onto_ref,
        "onto_sha": g.short(onto_ref, wt),
        "source_ref": source_ref,
        "source_sha": g.short(source_ref, wt),
        "source_why": why,
        "upstream": repo_cfg["community_main"],
        "started": _now(),
        "resolutions": [],
        "handoffs": [],
        "drops": [],
        "state": "running",
    }
    if task["kind"] == "rebase":
        sess["expected"] = g.subjects("%s..%s" % (repo_cfg["community_main"], source_ref), wt)
        rc, text = g.git(["rebase", "--onto", onto_ref, repo_cfg["community_main"],
                          "--empty=stop"], wt, check=False, timeout=3600)
    else:
        rc, text = g.git(["merge", "--no-edit", onto_ref], wt, check=False, timeout=1800)

    view = _settle(sess, wt, rc, text)
    state = _load()
    state["owner_pid"] = os.getppid()
    state["current"] = "%s/%s" % (repo_name, task_name)
    state["sessions"][state["current"]] = sess
    _save(state)
    view["source"] = "%s（%s）" % (source_ref, why)
    return view


def _current(cfg):
    state = _load()
    key = state.get("current")
    if not key or key not in state["sessions"]:
        raise GitError("没有进行中的 resolve 会话，先跑 `resolve start`")
    sess = state["sessions"][key]
    repo_cfg, _task = _find(cfg, sess["repo"], sess["task"])
    return state, key, sess, repo_cfg["worktree"]


def status(cfg):
    state, _key, sess, wt = _current(cfg)
    if sess["state"] == "done":
        return {"state": "done", "head": sess.get("head"),
                "resolved": len(sess["resolutions"])}
    if not g.in_progress(wt):
        return {"state": sess["state"], "detail": sess.get("last_output", "")[-1000:]}
    return _conflict_view(wt, sess)


def resolve_continue(cfg, basis, confidence, note, allow_empty=False, add_paths=None):
    """确认这一处已经解好，往下走一步。"""
    state, key, sess, wt = _current(cfg)
    if not g.in_progress(wt):
        raise GitError("当前没有停在冲突上（state=%s）" % sess["state"])
    if basis not in BASIS:
        raise GitError("basis 必须是 %s 之一" % (BASIS,))
    if confidence not in CONFIDENCE:
        raise GitError("confidence 必须是 %s 之一" % (CONFIDENCE,))
    if not note or len(note.strip()) < 8:
        raise GitError("note 必须写清依据（至少 8 个字），它会进报告给人复核")

    entries = g.conflict_entries(wt, "merge" if sess["kind"] == "merge" else "rebase")
    paths_now = [e["path"] for e in entries]

    # 规矩 2：还留着 <<<<<<< 就不给 add。把"解了一半就继续"挡在这里，
    # 比事后在体检里发现要便宜得多。
    bad = g.has_conflict_markers(wt, paths_now)
    if bad:
        raise GitError("这些文件里还留着冲突标记，拒绝继续：\n  %s" % "\n  ".join(bad))

    for entry in entries:
        full = os.path.join(wt, entry["path"])
        if os.path.exists(full):
            g.git(["add", "--", entry["path"]], wt)
        else:
            g.git(["rm", "-q", "--", entry["path"]], wt, check=False)

    # 只 stage 冲突文件是不够的：重贴落点（DU 那类）的正确解法是删掉死文件、
    # 把逻辑写进**另一个**文件，那处编辑不在冲突清单里，漏掉就等于白解。
    g.git(["add", "-u"], wt)

    # 新建的文件要显式报备。这棵 worktree 每轮开头都 clean 过，所以冒出来的
    # untracked 一定是这一步造的 —— 要么是有意新增，要么是手滑留下的临时文件，
    # 两者必须由调用方分清楚，不能默默打包进 commit。
    untracked = [ln[3:].strip() for ln in
                 g.out(["status", "--porcelain", "--untracked-files=all"], wt).splitlines()
                 if ln.startswith("?? ")]
    unexpected = [u for u in untracked if u not in (add_paths or [])]
    if unexpected:
        raise GitError(
            "工作区里有没报备的新文件，拒绝继续（怕把临时文件打进 commit）：\n  %s\n"
            "确实要带上就加 --add <path>，是垃圾就先删掉。" % "\n  ".join(unexpected))
    for path in (add_paths or []):
        if os.path.exists(os.path.join(wt, path)):
            g.git(["add", "--", path], wt)

    # 规矩 3：解完和 HEAD 没差别 → 这个 patch 正在消失，必须显式走 drop。
    if sess["kind"] == "rebase" and g.git(["diff", "--cached", "--quiet", "HEAD"],
                                          wt, check=False)[0] == 0:
        if not allow_empty:
            raise GitError(
                "解完之后这个 commit 会变成空的 —— 也就是这个 Ant patch 就此消失。\n"
                "如果确认是上游已经吸收了，走 `resolve drop --reason '<依据>'`；\n"
                "如果是落点挪了需要重贴，走 `resolve stop --reason '...'` 交给人。")

    # 先把"解的是哪个 commit"记下来 —— continue 之后 REBASE_HEAD 就变了。
    record = {
        "commit": (g.rebase_head(wt) or {"sha": "-", "subject": "merge"}),
        "files": entries,
        "basis": basis,
        "confidence": confidence,
        "note": note.strip(),
        "added": sorted(add_paths or []),
        "staged": [ln[3:].strip() for ln in
                   g.out(["status", "--porcelain", "--untracked-files=no"], wt).splitlines()],
        "at": _now(),
    }

    if sess["kind"] == "rebase":
        rc, text = g.git(["rebase", "--continue"], wt, check=False, timeout=3600)
    else:
        rc, text = g.git(["commit", "--no-edit"], wt, check=False, timeout=600)

    view = _settle(sess, wt, rc, text)

    # **动作落地之后**才记账。先记后做的话，commit 被钩子挡下这种情况会在报告里
    # 留下一条"已解决"，而那个冲突其实还在原地 —— 比不记更糟。
    advanced = view["state"] != "conflict" or view.get("commit", {}).get("sha") != record["commit"]["sha"]
    if advanced:
        sess["resolutions"].append(record)
    else:
        view["warning"] = "这一步没能推进（见 last_output），解法未记账；修掉原因后重试"
    state["sessions"][key] = sess
    _save(state)
    return view


def drop(cfg, reason):
    """确认这个 patch 上游已经吸收，让它退役。**唯一**会调用 rebase --skip 的地方。"""
    state, key, sess, wt = _current(cfg)
    if not g.in_progress(wt):
        raise GitError("当前没有停在冲突上")
    if not reason or len(reason.strip()) < 12:
        raise GitError("drop 要写清依据（至少 12 个字）：凭什么认定上游已经吸收了")

    head = g.rebase_head(wt) or {"sha": "-", "subject": "(unknown)"}
    sess["drops"].append({"commit": head, "reason": reason.strip(), "at": _now()})
    rc, text = g.git(["rebase", "--skip"], wt, check=False, timeout=3600)
    view = _settle(sess, wt, rc, text)
    state["sessions"][key] = sess
    _save(state)
    return view


def stop(cfg, reason):
    """解不动，交给人。整个会话到此为止，树回到干净状态。"""
    state, key, sess, wt = _current(cfg)
    # merge 没有"正在应用的那个 commit"，REBASE_HEAD 在这时的值是没有意义的 ——
    # 直接报出来会让报告看起来像"某个 Ant patch 解不动"，其实是整个 merge 解不动。
    if sess["kind"] == "merge":
        head = {"sha": sess["source_sha"],
                "subject": "merge %s into %s" % (sess["onto_ref"], sess["source_ref"])}
    else:
        head = g.rebase_head(wt) if g.in_progress(wt) else None
    sess["handoffs"].append({
        "commit": head or {"sha": "-", "subject": "-"},
        "files": g.conflict_entries(wt, "merge" if sess["kind"] == "merge" else "rebase"),
        "reason": (reason or "").strip(),
        "at": _now(),
    })
    sess["state"] = "handoff"
    g.abort_any(wt)
    state["sessions"][key] = sess
    state["current"] = None
    _save(state)
    return {"state": "handoff", "resolved": len(sess["resolutions"]),
            "reason": reason, "next": "这个任务今天到此为止，报告里会标成待人工"}


def finish(cfg):
    """体检 + 落候选分支。体检不过不代表失败，但会在报告里标出来。"""
    state, key, sess, wt = _current(cfg)
    if sess["state"] != "done":
        raise GitError("还没跑完（state=%s），不能 finish" % sess["state"])

    entry = {
        "name": sess["task"],
        "kind": sess["kind"],
        "onto_ref": sess["onto_ref"],
        "onto_sha": sess["onto_sha"],
        "conflicts": [],
        "empty_dropped": [],
        "explicit_drops": [d["commit"] for d in sess["drops"]],
        "expected_patches": sess.get("expected", []),
        "missing_patches": [],
        "alignment": {"checked": False},
    }
    if sess["kind"] == "rebase":
        entry["landed_patches"] = g.subjects("%s..HEAD" % sess["onto_ref"], wt)
        landed = {p["subject"] for p in entry["landed_patches"]}
        dropped = {d["commit"]["subject"] for d in sess["drops"]}
        entry["missing_patches"] = [
            p for p in entry["expected_patches"]
            if p["subject"] not in landed and p["subject"] not in dropped
        ]
        entry["alignment"] = tasks._alignment(
            wt, sess["upstream"], sess["source_ref"], sess["onto_ref"], g.rev("HEAD", wt))

    touched = sorted({f["path"] for r in sess["resolutions"] for f in r["files"]})
    verify.verify(entry, wt, syntax_files=touched)

    branch = candidate_branch(sess["repo"], sess["task"])
    g.git(["branch", "-f", branch, "HEAD"], wt)

    sess["candidate"] = branch
    sess["entry"] = entry
    sess["state"] = "finished"
    sess["finished"] = _now()
    state["sessions"][key] = sess
    state["current"] = None
    _save(state)

    return {
        "state": "finished",
        "candidate": branch,
        "head": entry.get("landed_patches") and g.short("HEAD", wt) or g.short("HEAD", wt),
        "resolved": len(sess["resolutions"]),
        "dropped": len(sess["drops"]),
        "missing": len(entry["missing_patches"]),
        "verified": entry["verified"],
        "checks_failed": [c["name"] for c in entry["checks"] if not c["ok"]],
        "alignment": entry["alignment"],
    }


def abort(cfg):
    state, key, sess, wt = _current(cfg)
    g.abort_any(wt)
    sess["state"] = "aborted"
    state["sessions"][key] = sess
    state["current"] = None
    _save(state)
    return {"state": "aborted"}


def sessions():
    return _load().get("sessions", {})
