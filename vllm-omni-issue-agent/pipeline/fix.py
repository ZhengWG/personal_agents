"""修复会话：给一个 issue 开本地分支 + 隔离 worktree，提交时把规矩卡死。

- 分支 `issue-fix/<号>-<slug>` 从社区 main 拉，**不设上游、不推送**。
- worktree 在 ~/.cache/vllm-omni-issue-agent/issue-<号>/，**绝不碰主 checkout**。
- 提交只能走 `agent.py fix commit`：自动 `-s`（上游要 DCO），拒绝 AI 署名，
  拒绝冲突标记和没报备的新文件。
"""
import datetime
import os
import re
import subprocess

from . import gh, paths, report

# 仓库装的 pre-commit 钩子要整套 mypy 环境，Mac 上跑不起来；lint 在 pod 里显式跑，
# 结果写进修复报告。
NO_HOOKS = "core.hooksPath=/dev/null"
# 上游 docs/contributing/README.md 的 PR 分类前缀
TITLE_PREFIX = re.compile(r"^\[(Bugfix|CI/Build|Doc|Model|Frontend|Kernel|Core|Hardware|Misc)\]")
# 用户的全局规则：commit 里不留任何 AI 署名
AI_MARK = re.compile(r"(?im)^co-authored-by:.*\b(claude|anthropic|copilot|gpt|codex|cursor|ai)\b"
                     r"|generated (with|by)\b|claude\.ai/code|\U0001F916")
CONFLICT = re.compile(r"^(<{7}|>{7})( |$)", re.M)


class FixError(RuntimeError):
    pass


def git(args, cwd, check=True, extra=None):
    proc = subprocess.run(["git", "-c", NO_HOOKS] + (extra or []) + list(args), cwd=cwd,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if check and proc.returncode != 0:
        raise FixError("git %s (rc=%d)\n%s" % (" ".join(args), proc.returncode, proc.stdout.strip()))
    return proc.stdout.strip()


def slugify(title):
    body = re.sub(r"^\s*(\[[^\]]*\]\s*:?\s*)+", "", title)
    words = re.findall(r"[A-Za-z0-9]+", body.lower())
    return "-".join(words)[:40].strip("-") or "fix"


def _alive(owner):
    """owner 形如 run-<pid>；进程不在了就算会话已结束。"""
    try:
        os.kill(int(str(owner).rsplit("-", 1)[-1]), 0)
        return True
    except (ValueError, OSError):
        return False


def fetch_issue(cfg, number):
    issue = gh.issue(cfg["upstream"], number)
    if "pull_request" in issue:
        raise FixError("#%d 是 PR，不是 issue" % number)
    events = gh.timeline(cfg["upstream"], number)
    found = gh.claims(cfg["upstream"], events)
    path = paths.issue_file(number)
    paths.save_text(path, report.issue_markdown(issue, events, found, gh.status_of(found)))
    return issue, found, path


def start(cfg, number, owner):
    cur = paths.load(paths.FIX)
    if cur and cur.get("issue") != number and cur.get("owner") != owner and _alive(cur.get("owner")):
        raise FixError("另一个修复会话还在跑：#%s（%s）" % (cur["issue"], cur["owner"]))

    repo = cfg["repo"]
    git(["fetch", "-q", cfg["community_remote"], "main"], repo)
    issue, found, issue_md = fetch_issue(cfg, number)

    prefix = "%s%d-" % (cfg["branch_prefix"], number)
    existing = git(["for-each-ref", "--format=%(refname:short)", "refs/heads/%s*" % prefix],
                   repo).split()
    branch = existing[0] if existing else prefix + slugify(issue["title"])
    wt = os.path.join(cfg["worktree_root"], "issue-%d" % number)

    if os.path.isdir(wt):
        head = git(["rev-parse", "--abbrev-ref", "HEAD"], wt)
        if head != branch:
            raise FixError("%s 已存在但在分支 %s 上（期望 %s），手动看一眼" % (wt, head, branch))
    else:
        git(["worktree", "prune"], repo)
        os.makedirs(cfg["worktree_root"], exist_ok=True)
        if existing:
            git(["worktree", "add", "-q", wt, branch], repo)
        else:
            git(["worktree", "add", "-q", "--no-track", "-b", branch, wt, cfg["base"]], repo)

    session = {
        "issue": number,
        "title": issue["title"],
        "url": issue["html_url"],
        "branch": branch,
        "worktree": wt,
        "base": git(["merge-base", "HEAD", cfg["base"]], wt),
        "main": git(["rev-parse", cfg["base"]], repo),
        "resumed": bool(existing),
        "issue_file": issue_md,
        "claim_status": gh.status_of(found),
        "started": datetime.datetime.now().isoformat(timespec="seconds"),
        "owner": owner,
    }
    paths.save(paths.FIX, session)
    return session


def current():
    sess = paths.load(paths.FIX)
    if not sess:
        raise FixError("没有修复会话（先 agent.py fix start <号>）")
    return sess


def commit(cfg, message, add):
    sess = current()
    wt = sess["worktree"]
    subject = message.strip().splitlines()[0]
    if not TITLE_PREFIX.match(subject):
        raise FixError("标题要以上游的 PR 分类前缀开头，如 [Bugfix]：%r" % subject)
    if AI_MARK.search(message):
        raise FixError("commit message 里不写 AI 署名 / 生成说明")

    untracked = git(["ls-files", "--others", "--exclude-standard"], wt).splitlines()
    unreported = [p for p in untracked if p not in add]
    if unreported:
        raise FixError("有没报备的新文件（要带上就 --add，临时文件请删掉）：\n  "
                       + "\n  ".join(unreported))
    for path in add:
        git(["add", "--", path], wt)
    git(["add", "-u"], wt)
    staged = git(["diff", "--cached", "--name-only"], wt).splitlines()
    if not staged:
        raise FixError("没有要提交的改动")
    for path in staged:
        full = os.path.join(wt, path)
        if os.path.isfile(full):
            with open(full, encoding="utf-8", errors="replace") as fh:
                if CONFLICT.search(fh.read()):
                    raise FixError("%s 里还有冲突标记" % path)
    proc = subprocess.run(["git", "-c", NO_HOOKS, "commit", "-q", "-s", "-F", "-"], cwd=wt,
                          input=message.strip() + "\n", text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        raise FixError("git commit 失败：%s" % proc.stdout.strip())
    return {"sha": git(["rev-parse", "--short", "HEAD"], wt), "subject": subject, "files": staged}


def summary(cfg):
    sess = current()
    wt = sess["worktree"]
    commits = git(["log", "--format=%h %s", "%s..HEAD" % sess["base"]], wt).splitlines()
    dirty = git(["status", "--porcelain"], wt).splitlines()
    fix_report = paths.fix_report_path(sess["issue"])
    return dict(sess, commits=commits, dirty=dirty,
                report=fix_report if os.path.exists(fix_report) else None)
