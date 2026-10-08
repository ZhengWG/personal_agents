"""release 独有提交审计 —— 找出只提交在 release 分支、没回灌 delta 来源的修复。

为什么需要它：delta 对齐只能证明"结果 ≡ 来源"，证明不了来源本身是全的。
两个仓库都实际撞上过：
  - vllm-ant：DeepGEMM 的 cmake 修复只推到了 public_tracker_daily / release，
    public_tracker 上没有，照它出的 v0.30.0 候选就少了一个 patch；
  - vllm-omni：三个引擎修复（SHM 回收 / 设备锁 / PR56）直接提交在
    ant/releases/v0.26.0 上，下一版 release 会静默丢掉它们。
两次都是人工拿上一版 release 逐个比对才发现的。这里把那次比对固化下来。
"""
import re

from . import gitutil as g

_REL_RE = re.compile(r"v(\d+)\.(\d+)\.(\d+)(?:rc(\d+))?$")
MAX_LINES_PER_COMMIT = 12


def _norm_subject(subject):
    """去掉 (#1234) 和挤进标题行的 Signed-off-by —— v0.26.0 上就有这种标题。"""
    subject = re.split(r"\s+Signed-off-by:", subject)[0]
    return re.sub(r"\s*\(#\d+\)\s*$", "", subject).strip()


def _upstream_subject(subject):
    """内部 PR 合入时会加 `PullRequest: 56 ` 前缀，和上游同一个 PR 的标题就对不上了。

    实测：omni 的 PR56 与上游 #7245 标题只差这个前缀，却被误报成 release 独有。
    """
    return re.sub(r"^PullRequest:\s*\d+\s+", "", subject).strip()


def _defined_names(repo, sha):
    body = g.out(["show", "--format=", sha], repo)
    # 用 [ \t] 而不是 \s：\s 会吃掉换行，把「+ 空行」后面那行上下文里的 def 也算成新增。
    return sorted(set(re.findall(r"^\+[ \t]*(?:async[ \t]+)?def[ \t]+(\w+)[ \t]*\(", body, re.M)))


def _release_branches(repo, remote, prefix):
    rows = []
    ref_prefix = "refs/remotes/%s/%s" % (remote, prefix)
    for line in g.out(["for-each-ref", "--format=%(refname)", ref_prefix], repo).splitlines():
        name = line[len("refs/remotes/%s/" % remote):]
        m = _REL_RE.search(name)
        if not m:
            continue
        major, minor, patch, rc = m.groups()
        key = (int(major), int(minor), int(patch), 0 if rc else 1, int(rc or 0))
        tag = name[len(prefix):]
        rows.append((key, "%s/%s" % (remote, name), tag))
    rows.sort(reverse=True)
    return rows


def _base_of(repo, branch, tag, community_main):
    for cand in (tag, tag + "rc1"):
        if g.ref_exists(cand, repo) and g.git(
                ["merge-base", "--is-ancestor", cand, branch], repo, check=False)[0] == 0:
            return cand
    return g.out(["merge-base", branch, community_main], repo)


def _added_lines(repo, sha):
    body = g.out(["show", "--format=", sha], repo)
    lines = [ln[1:].strip() for ln in body.splitlines()
             if ln.startswith("+") and not ln.startswith("+++") and len(ln[1:].strip()) > 25]
    return lines[:MAX_LINES_PER_COMMIT]


def _upstream_has(repo, community_main, sha, subject):
    """这个提交是不是上游 PR 的 backport —— 是的话新 base 自带，不算缺口。"""
    up_subject = _upstream_subject(subject)
    if up_subject and g.out(["log", "-1", "--format=%h", "-F", "--grep", up_subject, community_main], repo):
        return True, "上游有同名提交"
    # 上游合同一个修复时常改标题、改注释，逐行比对会失手（实测 omni 的 SHM 回收：
    # 上游 #8082 换了标题，新增行只命中 2/12，但五个新方法名一个不差）。
    names = _defined_names(repo, sha)
    # git grep -E 是 POSIX ERE，macOS 上不认 \s，必须写 [[:space:]]。
    if names and all(g.git(["grep", "-q", "-E", r"def[[:space:]]+%s[[:space:]]*\(" % n, community_main, "--"],
                           repo, check=False)[0] == 0 for n in names):
        return True, "新增函数 %d/%d 已在上游（%s），需人工确认实现等价" % (
            len(names), len(names), ", ".join(names[:4]))
    lines = _added_lines(repo, sha)
    if not lines:
        return False, ""
    hit = sum(1 for ln in lines if g.git(
        ["grep", "-q", "-F", "-e", ln, community_main, "--"], repo, check=False)[0] == 0)
    if hit * 10 >= len(lines) * 8:
        return True, "新增行 %d/%d 已在上游" % (hit, len(lines))
    return False, "新增行仅 %d/%d 在上游" % (hit, len(lines))


def audit(repo_cfg):
    """拿最近一个**非空**的 ant release 分支，对照 delta 来源找缺口。

    空壳（只建了分支、还没 rebase 的，如 omni 的 v0.29.0rc1/v0.30.0rc1）跳过，
    它们里面没有任何可比对的提交，拿它们比只会得出"一切正常"的假结论。
    """
    repo = repo_cfg["repo"]
    main = repo_cfg["community_main"]
    prefix = repo_cfg.get("release_branch_prefix", "ant/releases/")
    delta_subjects = {_norm_subject(r["subject"]) for r in
                      g.subjects("%s..%s" % (main, repo_cfg["delta_source"]), repo)}

    result = {"branch": None, "base": None, "skipped_empty": [], "release_only": [], "backports": []}
    for _key, branch, tag in _release_branches(repo, repo_cfg["ant_remote"], prefix):
        base = _base_of(repo, branch, tag, main)
        commits = g.subjects("%s..%s" % (base, branch), repo)
        if not commits:
            result["skipped_empty"].append(branch)
            continue
        result["branch"], result["base"] = branch, base[:12]
        for c in commits:
            subj = _norm_subject(c["subject"])
            if subj in delta_subjects:
                continue
            upstream, why = _upstream_has(repo, main, c["sha"], subj)
            row = {"sha": c["sha"], "subject": subj, "why": why}
            (result["backports"] if upstream else result["release_only"]).append(row)
        break
    return result
