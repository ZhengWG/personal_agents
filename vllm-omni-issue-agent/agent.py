#!/usr/bin/env python3
"""vllm-omni-issue-agent 的唯一 CLI。

每日分诊（run.sh 默认模式）：
    agent.py scan                       搜社区新 bug、读 timeline 判断有没有人在做 → candidates.json + 报告
    agent.py issue <号>                  拉一个 issue 的正文和全部评论到 state/issues/<号>.md
    agent.py triage add <号> --verdict fix|maybe|skip --cards K --model M --effort S|M|L --reason "…"
    agent.py triage list
    agent.py render                     用当前候选 + 分诊重新渲染报告（保留 Claude 写的分析）
    agent.py notify                     macOS 通知
    agent.py status                     配置 + 上一轮摘要

手动修复（run.sh --fix <号>）：
    agent.py fix start <号>              拉本地分支 + 隔离 worktree
    agent.py fix commit -m "[Bugfix] …" [--add 新文件]
    agent.py fix status
    agent.py pod up --cards K [--node N]  建 pod、挑空卡并占住
    agent.py pod sync                   把 worktree 当前内容搬进 pod
    agent.py pod prep [--model M …]     装环境 + 拉模型（全程占着卡）
    agent.py pod run [--gpu] [--wait S] -- <命令>   后台跑；--gpu 才放卡
    agent.py pod wait <id> [--wait S] / pod log <id> [--grep P]
    agent.py pod exec -- <短命令>        同步跑，不放卡
    agent.py pod status | gpus | down [--keep|--stale] | template --from <参考对象>

只做机械动作：能不能修、怎么修由 Claude 按 .claude/skills/vllm-omni-issue.md 判断。
不推送、不在 GitHub 上评论 / 认领 / 开 PR。
"""
import argparse
import datetime
import json
import os
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline import fix, paths, pod, report, scan, triage   # noqa: E402

os.environ.setdefault("GIT_TERMINAL_PROMPT", "0")
os.environ.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new")


def _emit(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))
    return 0


def _write_report(cands):
    cfg = paths.load_config()
    body = report.render(cands, triage.current(), cfg["max_cards"])
    target = paths.report_path(cands["date"])
    os.makedirs(paths.REPORT_DIR, exist_ok=True)
    body = report.keep_analysis(target, body)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(body)
    return target


# ---------------------------------------------------------------- 每日分诊 ----

def cmd_scan(args):
    cfg = paths.load_config()
    cands = scan.run(cfg, read_timeline=not args.no_timeline)
    target = _write_report(cands)
    print("报告：%s" % target)
    print("摘要：%s" % report.summary_line(cands))
    print(cands["http"])
    return 0


def cmd_issue(args):
    cfg = paths.load_config()
    path = paths.issue_file(args.number)
    fresh = os.path.exists(path) and datetime.date.fromtimestamp(
        os.path.getmtime(path)).isoformat() == paths.today()
    if args.refresh or not fresh:
        _, _, path = fix.fetch_issue(cfg, args.number)
    with open(path, encoding="utf-8") as fh:
        print(fh.read())
    return 0


def cmd_triage(args):
    cfg = paths.load_config()
    if args.verb == "add":
        return _emit(triage.add(cfg, args.number, args.verdict, args.cards, args.model,
                                args.effort, args.reason))
    return _emit(triage.current())


def cmd_render(args):
    cands = paths.load(paths.CANDIDATES)
    if not cands:
        sys.exit("还没扫描过（%s 不存在）" % paths.CANDIDATES)
    print(_write_report(cands))
    return 0


def cmd_notify(args):
    if args.fix:
        title = "vLLM-Omni #%s 修复" % args.fix
    else:
        cands = paths.load(paths.CANDIDATES)
        title = "vLLM-Omni issue 分诊"
        if cands and not args.message:
            args.message = report.summary_line(cands, triage.current())
    body = args.message or ""
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')       # noqa: E731
    subprocess.run(["/usr/bin/osascript", "-e", 'display notification "%s" with title "%s"'
                    % (esc(body[:230]), esc(title))], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("已通知：%s — %s" % (title, body))
    return 0


def cmd_status(args):
    cfg = paths.load_config()
    cands = paths.load(paths.CANDIDATES)
    if args.unclaimed:
        counts = cands.get("counts", {}) if cands else {}
        print(counts.get("unclaimed", 0) + counts.get("stale-claim", 0))
        return 0
    print("上游：%s，本地仓库 %s" % (cfg["upstream"], cfg["repo"]))
    print("单次最多占卡：%d；集群配置：%s" % (cfg["max_cards"], paths.local_file(cfg, "pod.json")))
    if cands:
        print("上一轮扫描：%s —— %s" % (cands["generated"], report.summary_line(cands, triage.current())))
        print("报告：%s" % paths.report_path(cands["date"]))
    sess = paths.load(paths.FIX)
    if sess:
        print("修复会话：#%s %s（%s）" % (sess["issue"], sess["branch"], sess["worktree"]))
    st = paths.load(paths.POD)
    if st:
        print("pod：%s 在 %s，卡 %s%s" % (st.get("pod") or st["name"], st["node"], st.get("gpus"),
                                      "（已放卡保留）" if st.get("kept") else ""))
    return 0


# ---------------------------------------------------------------- 修复 ----

def cmd_fix(args):
    cfg = paths.load_config()
    try:
        if args.verb == "start":
            owner = os.environ.get("OMNI_ISSUE_OWNER") or "manual-%d" % os.getppid()
            return _emit(fix.start(cfg, args.number, owner))
        if args.verb == "commit":
            return _emit(fix.commit(cfg, args.message, args.add))
        if args.verb == "status":
            return _emit(fix.summary(cfg))
    except fix.FixError as exc:
        print("✗ %s" % exc, file=sys.stderr)
        return 2
    return 2


# ---------------------------------------------------------------- pod ----

def _command(parts):
    parts = parts[1:] if parts[:1] == ["--"] else parts
    if not parts:
        sys.exit("缺命令：agent.py pod run -- <命令>")
    # 整条命令建议用一个引号包起来传；拆成多个参数时按 shell 规则重新转义
    return parts[0] if len(parts) == 1 else shlex.join(parts)


def cmd_pod(args):
    cfg = paths.load_config()
    local = paths.load_local(cfg)
    try:
        if args.verb == "template":
            return _emit(pod.make_template(cfg, local, args.ref))
        if args.verb == "up":
            return _emit(pod.up(cfg, local, args.cards, args.node))
        if args.verb == "down":
            if args.stale:
                return _emit({"removed": pod.down_stale(local)})
            return _emit(pod.down(local, keep=args.keep))
        if args.verb == "list":
            return _emit({"ours": pod.ours(local), "current": paths.load(paths.POD)})

        st = pod.require(local)
        if args.verb == "status":
            return _emit(dict(st, holder=pod.helper(st, ["status"])))
        if args.verb == "gpus":
            rows = pod.helper(st, ["gpus"])["gpus"]
            mine = set(st.get("gpus") or [])
            for r in rows:
                print("%s %d  %6d / %6d MiB  util %s%%" % ("★" if r["index"] in mine else " ",
                      r["index"], r["used_mib"], r["total_mib"], r["util"]))
            return 0
        if args.verb == "hold":
            return _emit(pod.helper(st, ["hold"], timeout=400))
        if args.verb == "release":
            return _emit(pod.helper(st, ["release"]))
        if args.verb == "sync":
            return _emit(pod.sync(cfg, st, fix.current()))
        if args.verb == "exec":
            rc, out = pod.shell(st, _command(args.command), timeout=args.timeout)
            print(out)
            return rc
        if args.verb in ("run", "prep"):
            if args.verb == "prep":
                print(json.dumps(pod.sync(cfg, st, fix.current()), ensure_ascii=False))
                command, gpu = pod.prep_command(args.model), False
                run_id = "prep-" + datetime.datetime.now().strftime("%m%d-%H%M%S")
            else:
                command, gpu, run_id = _command(args.command), args.gpu, None
                # 改完代码忘了 sync 就会拿旧代码测出错误结论，所以默认每次都同步
                if not args.no_sync and paths.load(paths.FIX):
                    print(json.dumps(pod.sync(cfg, st, fix.current()), ensure_ascii=False))
            run_id = pod.run(st, command, gpu=gpu, run_id=run_id)
            print("[pod] 已在后台启动 %s（%s）" % (run_id, "放卡跑" if gpu else "占着卡跑"))
            return _finish_wait(st, run_id, args.wait)
        if args.verb == "wait":
            return _finish_wait(st, args.id, args.wait)
        if args.verb == "log":
            print(pod.log(st, args.id, args.n, args.grep))
            return 0
    except (pod.PodError, fix.FixError) as exc:
        print("✗ %s" % exc, file=sys.stderr)
        return 2
    return 2


def _finish_wait(st, run_id, budget):
    if budget <= 0:
        print("[pod] 不等：agent.py pod wait %s" % run_id)
        return 0
    state, rc = pod.wait(st, run_id, budget)
    if state == "done":
        print("[pod] %s 结束 rc=%s" % (run_id, rc))
        return rc
    if state == "running":
        print("[pod] %s 还在跑（等了 %ds）：agent.py pod wait %s" % (run_id, budget, run_id))
        return 124
    print("[pod] %s 状态 %s —— runner 进程没了，看 pod log %s" % (run_id, state, run_id))
    return 3


# ---------------------------------------------------------------- main ----

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scan", help="搜社区新 bug 并判断认领情况")
    p.add_argument("--no-timeline", action="store_true", help="不读 timeline（调试，省 API 次数）")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("issue", help="看一个 issue 的全文（今天扫过的直接读本地，不调 API）")
    p.add_argument("number", type=int)
    p.add_argument("--refresh", action="store_true", help="强制重新拉（要最新评论时）")
    p.set_defaults(func=cmd_issue)

    p = sub.add_parser("triage", help="记录 / 查看分诊结论")
    tv = p.add_subparsers(dest="verb", required=True)
    t = tv.add_parser("add")
    t.add_argument("number", type=int)
    t.add_argument("--verdict", required=True, choices=list(triage.VERDICTS))
    t.add_argument("--cards", type=int, help="复现 + 验证要几张卡；只跑 CPU 测试填 0")
    t.add_argument("--model", help="复现要用的 HF 模型 id")
    t.add_argument("--effort", required=True, choices=list(triage.EFFORTS))
    t.add_argument("--reason", required=True, help="一两句：为什么修 / 为什么不修")
    tv.add_parser("list")
    p.set_defaults(func=cmd_triage)

    p = sub.add_parser("render", help="重新渲染报告")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("notify", help="macOS 通知")
    p.add_argument("--message")
    p.add_argument("--fix", type=int, help="修复模式的通知")
    p.set_defaults(func=cmd_notify)

    p = sub.add_parser("status", help="配置 + 上一轮摘要")
    p.add_argument("--unclaimed", action="store_true", help="只打印可认领个数（未认领 + 认领已过期）")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("fix", help="修复会话")
    fv = p.add_subparsers(dest="verb", required=True)
    f = fv.add_parser("start")
    f.add_argument("number", type=int)
    f = fv.add_parser("commit")
    f.add_argument("-m", "--message", required=True)
    f.add_argument("--add", action="append", default=[], help="要带上的新文件（可重复）")
    fv.add_parser("status")
    p.set_defaults(func=cmd_fix)

    p = sub.add_parser("pod", help="GPU pod")
    pv = p.add_subparsers(dest="verb", required=True)
    q = pv.add_parser("template", help="从参考调试对象派生 pod 模板（存本机）")
    q.add_argument("--from", dest="ref", required=True)
    q = pv.add_parser("up")
    q.add_argument("--cards", type=int, required=True)
    q.add_argument("--node")
    q = pv.add_parser("down")
    q.add_argument("--keep", action="store_true", help="放卡但留着 pod")
    q.add_argument("--stale", action="store_true", help="清掉以前崩溃留下的、本 agent 建的对象")
    for name in ("list", "status", "gpus", "hold", "release", "sync"):
        pv.add_parser(name)
    q = pv.add_parser("exec")
    q.add_argument("--timeout", type=int, default=300)
    q.add_argument("command", nargs=argparse.REMAINDER)
    q = pv.add_parser("run")
    q.add_argument("--gpu", action="store_true", help="跑的时候放卡给这条命令用")
    q.add_argument("--no-sync", action="store_true", help="不先同步 worktree（另一条命令还在跑时用）")
    q.add_argument("--wait", type=int, default=540, help="最多等几秒（默认卡在 Bash 工具 10 分钟以内）")
    q.add_argument("command", nargs=argparse.REMAINDER)
    q = pv.add_parser("prep")
    q.add_argument("--model", action="append", default=[])
    q.add_argument("--wait", type=int, default=540)
    q = pv.add_parser("wait")
    q.add_argument("id")
    q.add_argument("--wait", type=int, default=540)
    q = pv.add_parser("log")
    q.add_argument("id")
    q.add_argument("-n", type=int, default=150)
    q.add_argument("--grep")
    p.set_defaults(func=cmd_pod)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
