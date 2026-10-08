"""git 薄封装 + 隔离 worktree 管理。

两条铁律：
  1. **绝不碰用户的主 checkout**。所有 rebase/merge 都在专用 worktree 里、在
     `rebase-agent/*` 临时分支上做。用户白天在主 checkout 上干活，agent 半夜
     跑 rebase，两者不能互相踩。
  2. **绝不留下半途状态**。任何异常路径都要能 abort 回干净树，否则第二天
     worktree 里挂着一个没做完的 rebase，后面每一轮都会失败。
"""
import os
import re
import subprocess


class GitError(RuntimeError):
    pass


# 仓库自带的 pre-commit 钩子（vllm-omni 上是全套 mypy）会在 commit 时跑起来并失败 ——
# 失败的大多是上游既有的类型问题，和这次 rebase 无关，但足以让整个 merge 提交不了。
# agent 产出的是**候选树**，不是要交付的提交，质量由 verify.py 自己把关，不借道钩子。
_NO_HOOKS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_no_hooks")


def git(args, cwd, check=True, timeout=1800):
    """跑一条 git，返回 (rc, stdout+stderr)。check=True 时非 0 抛 GitError。"""
    proc = subprocess.run(
        ["git", "-c", "core.hooksPath=%s" % _NO_HOOKS] + list(args),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
    )
    out = proc.stdout.strip()
    if check and proc.returncode != 0:
        raise GitError("git %s (rc=%d)\n%s" % (" ".join(args), proc.returncode, out))
    return proc.returncode, out


def out(args, cwd):
    return git(args, cwd)[1]


def rev(ref, cwd):
    return out(["rev-parse", "--verify", ref], cwd)


def ref_exists(ref, cwd):
    return git(["rev-parse", "--verify", "-q", ref + "^{commit}"], cwd, check=False)[0] == 0


def short(ref, cwd):
    return out(["rev-parse", "--short", ref], cwd)


def subject(ref, cwd):
    return out(["log", "-1", "--format=%s", ref], cwd)


def count(range_expr, cwd, no_merges=True):
    args = ["rev-list", "--count"]
    if no_merges:
        args.append("--no-merges")
    args.append(range_expr)
    return int(out(args, cwd))


def fetch(cwd, remotes):
    """抓远端。失败不静默 —— 基线抓错了，后面整轮 rebase 都是错的。

    `remotes` 是 (远端名, 要不要抓 tag) 的列表。**只有社区远端能带 tag**：
    版本 tag 只存在于 github 那一侧，对内网远端跑 --prune-tags 会把本地
    v0.2x 系列 tag 全部当成"远端已删"清掉，下一步选最新 RC 就会选错。
    """
    results = {}
    for remote, want_tags in remotes:
        args = ["fetch", remote, "--prune"]
        if want_tags:
            args += ["--tags", "--prune-tags", "--force"]
        else:
            args.append("--no-tags")
        rc, text = git(args, cwd, check=False, timeout=900)
        results[remote] = {"ok": rc == 0, "tags": want_tags, "output": text[-2000:]}
    return results


# --- worktree ---------------------------------------------------------------

def ensure_worktree(repo, path, base_ref):
    """准备隔离 worktree，detached 在 base_ref 上，工作区干净。

    幂等：已存在就复用（只 reset 到 base_ref），不存在才创建。复用能省掉
    每天重新 checkout 一整棵 ~200MB 的树。
    """
    git(["worktree", "prune"], repo, check=False)
    if not os.path.isdir(os.path.join(path, ".git")) and not os.path.isfile(
        os.path.join(path, ".git")
    ):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        git(["worktree", "add", "--detach", path, base_ref], repo, timeout=1800)
        return "created"
    reset_clean(path, base_ref)
    return "reused"


def in_progress(cwd):
    """当前是否卡在 rebase / merge / cherry-pick 中间。"""
    gitdir = out(["rev-parse", "--absolute-git-dir"], cwd)
    for marker in ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD"):
        if os.path.exists(os.path.join(gitdir, marker)):
            return marker
    return None


def abort_any(cwd):
    """无条件回到干净状态。每轮开始和结束都调它。"""
    marker = in_progress(cwd)
    if marker in ("rebase-merge", "rebase-apply"):
        git(["rebase", "--abort"], cwd, check=False)
    elif marker == "MERGE_HEAD":
        git(["merge", "--abort"], cwd, check=False)
    elif marker == "CHERRY_PICK_HEAD":
        git(["cherry-pick", "--abort"], cwd, check=False)
    return marker


def reset_clean(cwd, ref):
    abort_any(cwd)
    git(["checkout", "--detach", "-f", ref], cwd)
    git(["reset", "--hard", ref], cwd)
    git(["clean", "-fdx", "-e", ".venv", "-e", "__pycache__"], cwd, check=False)


def conflicted_files(cwd):
    text = out(["diff", "--name-only", "--diff-filter=U"], cwd)
    return [line for line in text.splitlines() if line.strip()]


def has_conflict_markers(cwd, files):
    """解决完之后的复查：留着 <<<<<<< 就 commit 是最典型的事故。"""
    bad = []
    for path in files:
        full = os.path.join(cwd, path)
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                body = fh.read()
        except OSError:
            continue
        if "\n<<<<<<< " in body or body.startswith("<<<<<<< "):
            bad.append(path)
    return bad


# --- 查询 ---------------------------------------------------------------------

_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:rc(\d+))?$")


def _tag_key(tag):
    """(major, minor, patch, is_final, rc) —— 正式 tag 排在同版本 rc 之前。

    不能用 `git tag --sort=-v:refname`：它把 v0.30.0rc2 排在 v0.30.0 前面
    （字典序 'rc2' > ''），于是"最新 release tag"会挑到 rc 而不是正式版。
    """
    m = _TAG_RE.match(tag)
    if not m:
        return None
    major, minor, patch, rc = m.groups()
    return (int(major), int(minor), int(patch), 0 if rc else 1, int(rc or 0))


def latest_release_tag(cwd, pattern):
    """按语义版本挑最新的 release tag，pattern 之外的杂 tag（如 vllmforascend-init-*）一律忽略。"""
    rx = re.compile(pattern)
    best, best_key = None, None
    for tag in out(["tag", "-l"], cwd).splitlines():
        tag = tag.strip()
        if not tag or not rx.match(tag):
            continue
        key = _tag_key(tag)
        if key is None:
            continue
        if best_key is None or key > best_key:
            best, best_key = tag, key
    return best


def subjects(range_expr, cwd, no_merges=True):
    args = ["log", "--format=%H\x1f%s"]
    if no_merges:
        args.append("--no-merges")
    args.append(range_expr)
    rows = []
    for line in out(args, cwd).splitlines():
        if "\x1f" in line:
            sha, subj = line.split("\x1f", 1)
            rows.append({"sha": sha[:10], "subject": subj})
    return rows


def rebase_head(cwd):
    """rebase 停下来时正在应用的那个 commit。停在空 commit 上时也有值。"""
    rc, sha = git(["rev-parse", "--verify", "-q", "REBASE_HEAD"], cwd, check=False)
    if rc != 0 or not sha:
        return None
    return {"sha": sha[:10], "subject": subject(sha, cwd)}


def conflict_excerpt(cwd, path, max_lines=60):
    """截出文件里的冲突段落，给 Claude 看的。整文件太大，只取 <<<<<<< 到 >>>>>>> 之间。"""
    full = os.path.join(cwd, path)
    try:
        with open(full, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    picked, inside = [], False
    for idx, line in enumerate(lines, 1):
        if line.startswith("<<<<<<< "):
            inside = True
        if inside:
            picked.append("%d: %s" % (idx, line))
        if line.startswith(">>>>>>> "):
            inside = False
            picked.append("...")
        if len(picked) >= max_lines:
            picked.append("...(截断)")
            break
    return picked


def normalized_diff(base, tip, cwd, pathspec=None):
    """diff 的内容行，去掉 hunk 行号和文件头 —— 两侧 base 不同时行号必然错位。

    对应 SKILL.md 验证第 4b 步的 norm()。返回 +/- 行列表。
    """
    args = ["diff", base, tip]
    if pathspec:
        args += ["--"] + list(pathspec)
    body = out(args, cwd)
    keep = []
    for line in body.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") or line.startswith("-"):
            keep.append(line)
    return keep


# --- 冲突分类 -----------------------------------------------------------------

# 只看文件名会把两种完全不同的事故混成一条：
#   UU = 同一段代码两边都改了 → 按 playbook 合并
#   上游把文件删了/挪走了 → patch 落点没了，要找新落点重贴（工作区里根本没有
#   <<<<<<< 标记，光看"冲突片段"会以为没信息）
#
# 关键坑：**rebase 会交换 ours/theirs**。回放时 "ours"(第一个字母) 是正在被
# 垒上去的新 base，"theirs"(第二个字母) 才是那个 Ant patch —— 和 merge 时正好相反。
# 同一个 DU 在两种模式下含义截然不同，所以按模式分两张表，别合并。
_KIND_REBASE = {
    "DD": "新 base 和 patch 都删除了这个文件",
    "AU": "只有新 base 新增（Ant patch 没有）",
    "UD": "Ant patch 删除了它，新 base 仍在修改",
    "UA": "由 Ant patch 新增，但落点和新 base 冲突（常见于上游挪了目录，git 按目录重命名把新文件搬了过去）",
    "DU": "新 base 已删除这个文件，而 Ant patch 还在改它 —— 落点没了，要找新落点重贴",
    "AA": "新 base 和 patch 各自新增了同名文件",
    "UU": "内容冲突（同一段两边都改）",
}

_KIND_MERGE = {
    "DD": "两侧都删除了这个文件",
    "AU": "只有 public_tracker 新增",
    "UD": "public_tracker 改了它，社区 main 删除了 —— 上游删/挪了文件",
    "UA": "只有社区 main 新增",
    "DU": "public_tracker 删除了它，社区 main 仍在修改",
    "AA": "两侧各自新增了同名文件",
    "UU": "内容冲突（同一段两边都改）",
}

CONFLICT_CODES = frozenset(_KIND_REBASE)


def conflict_entries(cwd, mode="rebase"):
    """带类型的冲突清单。比 conflicted_files() 多一个 code，别再只拿文件名。

    mode 必须如实传（rebase / merge），否则 ours/theirs 的解释会反过来。
    """
    table = _KIND_MERGE if mode == "merge" else _KIND_REBASE
    rows = []
    for line in out(["status", "--porcelain"], cwd).splitlines():
        if len(line) < 4:
            continue
        code = line[:2]
        if code not in CONFLICT_CODES:
            continue
        path = line[3:].strip()
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        rows.append({"path": path, "code": code, "kind": table[code]})
    return rows
