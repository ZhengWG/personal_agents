#!/usr/bin/env python3
"""vllm-rebase-agent 的唯一 CLI。

    agent.py run                    # 跑一轮演练，写 state/last-run.json + reports/<date>.md
    agent.py run --repo vllm-ant    # 只跑一个仓库
    agent.py run --no-fetch         # 不抓远端（调试用，基线是本地的）
    agent.py render                 # 用上一轮结果重新渲染报告
    agent.py notify                 # 按上一轮结果弹 macOS 通知
    agent.py status                 # 看配置 + 上一轮结果摘要
    agent.py playbook               # 只把各仓库的 skill 抠到 state/playbook/

只做机械动作，不做判断。冲突怎么解由 Claude 读 state/playbook/ 里的
ant-release-rebase skill 决定，追加到报告的「分析与建议」一节。
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pipeline import paths, report, resolve, tasks   # noqa: E402

# git 在 launchd 下不能弹任何交互：没有 tty，弹了就是挂到看门狗超时。
os.environ.setdefault("GIT_TERMINAL_PROMPT", "0")
os.environ["GIT_EDITOR"] = "true"
os.environ["GIT_SEQUENCE_EDITOR"] = "true"
os.environ.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new")


def _today():
    return datetime.date.today().isoformat()


def cmd_run(args):
    cfg = paths.load_config()
    if args.no_push:
        cfg["push_enabled"] = False

    selected = cfg["repos"]
    if args.repo:
        selected = [r for r in selected if r["name"] in args.repo]
        if not selected:
            sys.exit("没有匹配的仓库：%s（配置里有 %s）"
                     % (args.repo, [r["name"] for r in cfg["repos"]]))
    if args.task:
        for repo in selected:
            repo["tasks"] = [t for t in repo["tasks"] if t["name"] in args.task]

    started = time.time()
    run = {
        "date": _today(),
        "started": datetime.datetime.now().isoformat(timespec="seconds"),
        "push_enabled": cfg.get("push_enabled", False),
        "repos": [],
    }

    for repo_cfg in selected:
        print("=== %s ===" % repo_cfg["name"], flush=True)
        run["repos"].append(_run_one(cfg, repo_cfg, skip_fetch=args.no_fetch))

    run["elapsed"] = time.time() - started
    paths.save_state(run)

    os.makedirs(paths.REPORT_DIR, exist_ok=True)
    target = paths.report_path(run["date"])
    run["resolve"] = resolve.sessions()
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(report.render(run))

    print("")
    print("报告：%s" % target)
    print("摘要：%s" % report.summary_line(run))
    print("最严重：%s" % report.severity(run))
    return 0 if report.severity(run) != "error" else 1


def _run_one(cfg, repo_cfg, skip_fetch=False):
    if not skip_fetch:
        return tasks.run_repo(cfg, repo_cfg)
    original = tasks.g.fetch
    tasks.g.fetch = lambda cwd, remotes: {
        (r[0] if isinstance(r, (tuple, list)) else r): {"ok": True, "output": "(--no-fetch)"}
        for r in remotes
    }
    try:
        return tasks.run_repo(cfg, repo_cfg)
    finally:
        tasks.g.fetch = original


def _keep_analysis(target, body):
    """render 重写整个报告，Claude 已填的「分析与建议」要原样留住。

    run.sh 在 claude 结束后还会无条件 render 一次刷新事实部分，少了这一步
    就会把当轮刚写好的分析冲成占位符（10-09 到 10-13 每天都发生）。
    """
    if not os.path.exists(target):
        return body
    with open(target, encoding="utf-8") as fh:
        old = fh.read()
    head, sep, kept = old.partition(report.ANALYSIS_MARKER)
    if not sep:
        return body
    kept = kept.strip()
    if not kept or kept == report.ANALYSIS_PLACEHOLDER:
        return body
    head, sep, _ = body.partition(report.ANALYSIS_MARKER)
    if not sep:
        return body
    return "%s%s\n\n%s\n" % (head, sep, kept)


def cmd_render(args):
    run = paths.load_state()
    if not run:
        sys.exit("还没有跑过（%s 不存在）" % paths.STATE_FILE)
    run["resolve"] = resolve.sessions()
    body = report.render(run)
    if args.stdout:
        print(body)
        return 0
    target = paths.report_path(args.date or run["date"])
    os.makedirs(paths.REPORT_DIR, exist_ok=True)
    body = _keep_analysis(target, body)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(body)
    print(target)
    return 0


def cmd_push(args):
    """把解完冲突的候选树推上去 —— run.sh 在 claude 正常结束后调这一步。

    和 run 阶段的推送是两回事：那一步只能推"机械重放就干净"的任务，而
    daily/release 从来没干净过。这一步推的是人（Claude）解完之后的产物，
    所以闸门更严：除了验收全过，还要求没有交人工、没有低自信解法。

    不可逆的一步放在 run.sh 里由脚本调用，而不是让 claude 自己推 ——
    解冲突的和决定推不推的不该是同一个。
    """
    cfg = paths.load_config()
    run = paths.load_state()
    if not run:
        sys.exit("还没有跑过（%s 不存在）" % paths.STATE_FILE)

    sess_all = resolve.sessions()
    push_enabled = cfg.get("push_enabled", False)
    by_name = {r["name"]: r for r in cfg["repos"]}

    pushed = blocked = 0
    for repo_result in run.get("repos", []):
        repo_cfg = by_name.get(repo_result.get("name"))
        if not repo_cfg:
            continue
        ctx = {"latest_rc": repo_result.get("latest_rc"),
               "run_started": run.get("started")}
        for task in repo_cfg["tasks"]:
            if args.task and task["name"] not in args.task:
                continue
            key = "%s/%s" % (repo_cfg["name"], task["name"])
            sess = sess_all.get(key)

            if args.dry_run:
                blockers = tasks.resolved_push_blockers(
                    sess, task.get("push") or {}, push_enabled, run.get("started"))
                mark = "推" if not blockers else "跳过"
                print("[%s] %s%s" % (mark, key,
                                     "" if not blockers else " —— " + "；".join(blockers)))
                continue

            result = tasks.push_resolved(repo_cfg, task, sess, ctx, push_enabled)
            # 回写进 last-run.json，让报告里「推送」那一行反映的是最终结果，
            # 而不是机械阶段那句"结果不是 clean，拒绝推送"。
            for entry in repo_result.get("tasks", []):
                if entry.get("name") == task["name"]:
                    entry["push"] = result
                    break
            if result["done"]:
                pushed += 1
                print("[已推] %s → %s (%s)" % (key, result["ref"], result["head"][:10]))
            else:
                blocked += 1
                print("[未推] %s —— %s" % (key, result["reason"]))

    if not args.dry_run:
        paths.save_state(run)
        print("\n推送 %d 个，未推 %d 个" % (pushed, blocked))
    return 0


def cmd_notify(args):
    run = paths.load_state()
    if not run:
        sys.exit("还没有跑过")
    worst = report.severity(run)
    title = {
        "clean": "vLLM 每日 rebase ✅ 干净",
        "drifted": "vLLM 每日 rebase 🟠 delta 漂移",
        "conflicts": "vLLM 每日 rebase ⚠️ 有冲突",
        "dropped": "vLLM 每日 rebase 🔴 掉 patch",
        "error": "vLLM 每日 rebase 💥 执行失败",
        "skipped": "vLLM 每日 rebase ⏭️ 有跳过",
    }.get(worst, "vLLM 每日 rebase")
    # 推送失败不进 severity（它只表达 rebase 结果），但必须让人在标题上看见，
    # 否则开了 push_enabled 之后推不上去是无声的。
    if report.push_failures(run):
        title += " · 推送失败"
    body = args.message or report.summary_line(run)
    if args.quiet_when_clean and worst == "clean":
        print("clean，按 --quiet-when-clean 不打扰")
        return 0
    _osascript(title, body)
    print("已通知：%s — %s" % (title, body))
    return 0


def _osascript(title, body):
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')       # noqa: E731
    script = 'display notification "%s" with title "%s"' % (esc(body[:230]), esc(title))
    subprocess.run(["/usr/bin/osascript", "-e", script], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def cmd_status(args):
    cfg = paths.load_config()
    print("配置：%s" % paths.CONFIG)
    print("推送：%s" % ("开启" if cfg.get("push_enabled") else "关闭（只读演练）"))
    for repo in cfg["repos"]:
        print("  - %-14s %s" % (repo["name"], repo["repo"]))
        print("      worktree %s" % repo["worktree"])
        print("      tasks    %s" % ", ".join(t["name"] for t in repo["tasks"]))
    run = paths.load_state()
    if not run:
        print("\n还没有跑过。")
        return 0
    print("\n上一轮：%s（耗时 %ds，最严重 %s）"
          % (run.get("started"), int(run.get("elapsed", 0)), report.severity(run)))
    print("  %s" % report.summary_line(run))
    print("  报告 %s" % paths.report_path(run["date"]))
    return 0


def cmd_playbook(args):
    cfg = paths.load_config()
    for repo_cfg in cfg["repos"]:
        saved = tasks.extract_playbook(repo_cfg, repo_cfg["playbook_dir"])
        print("%s -> %d 个文件" % (repo_cfg["name"], len(saved)))
        for path in saved:
            print("   %s" % path)
    return 0


def _emit(payload):
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def cmd_resolve(args):
    cfg = paths.load_config()
    try:
        if args.verb == "start":
            return _emit(resolve.start(cfg, args.repo, args.task, args.source, args.force, args.onto))
        if args.verb == "status":
            return _emit(resolve.status(cfg))
        if args.verb == "continue":
            return _emit(resolve.resolve_continue(
                cfg, args.basis, args.confidence, args.note, args.allow_empty, args.add))
        if args.verb == "drop":
            return _emit(resolve.drop(cfg, args.reason))
        if args.verb == "stop":
            return _emit(resolve.stop(cfg, args.reason))
        if args.verb == "finish":
            return _emit(resolve.finish(cfg))
        if args.verb == "abort":
            return _emit(resolve.abort(cfg))
    except resolve.GitError as exc:
        print(json.dumps({"error": str(exc)}, indent=2, ensure_ascii=False))
        return 2
    return 2


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="跑一轮演练")
    run.add_argument("--repo", action="append", help="只跑指定仓库（可重复）")
    run.add_argument("--task", action="append", help="只跑指定任务（可重复）")
    run.add_argument("--no-fetch", action="store_true", help="不抓远端，用本地已有的 ref")
    run.add_argument("--no-push", action="store_true", help="强制关掉推送（配置已开时的保险）")
    run.set_defaults(func=cmd_run)

    render = sub.add_parser("render", help="用上一轮结果重新渲染报告")
    render.add_argument("--date", help="写到哪一天的报告文件")
    render.add_argument("--stdout", action="store_true", help="打到标准输出而不是写文件")
    render.set_defaults(func=cmd_render)

    notify = sub.add_parser("notify", help="弹 macOS 通知")
    notify.add_argument("--message", help="自定义正文")
    notify.add_argument("--quiet-when-clean", action="store_true", help="全绿就不打扰")
    notify.set_defaults(func=cmd_notify)

    push = sub.add_parser("push", help="推解完冲突的候选树（run.sh 在 claude 成功后调）")
    push.add_argument("--task", action="append", help="只推指定任务（可重复）")
    push.add_argument("--dry-run", action="store_true", help="只列出推/不推和原因")
    push.set_defaults(func=cmd_push)

    status = sub.add_parser("status", help="看配置和上一轮结果")
    status.set_defaults(func=cmd_status)

    pb = sub.add_parser("playbook", help="把各仓库的 skill 抠到 state/playbook/")
    pb.set_defaults(func=cmd_playbook)

    # resolve：一次停一个冲突，等解完再往下走。**没有 skip 动作** —— 解不动只能
    # stop 交给人，要让 patch 退役只能走 drop 并写明依据。
    rs = sub.add_parser("resolve", help="逐个解冲突，产出完整的候选分支")
    rv = rs.add_subparsers(dest="verb", required=True)

    p = rv.add_parser("start", help="开一轮：重放到第一个冲突处停下")
    p.add_argument("--repo", required=True)
    p.add_argument("--task", required=True)
    p.add_argument("--source", help="覆盖重放基线（默认自动挑依赖任务的候选分支）")
    p.add_argument("--onto", help="覆盖目标基线（如某个具体 tag）")
    p.add_argument("--force", action="store_true", help="无视会话锁（确认占用者已不在）")

    rv.add_parser("status", help="当前停在哪个冲突上")

    p = rv.add_parser("continue", help="确认这一处已解好，往下走")
    p.add_argument("--basis", required=True, choices=list(resolve.BASIS),
                   help="依据：playbook 已有结论 / new 新判断 / reanchor 重新定位落点 / trivial 空白漂移")
    p.add_argument("--confidence", required=True, choices=list(resolve.CONFIDENCE))
    p.add_argument("--note", required=True, help="解法和依据，会进报告给人复核")
    p.add_argument("--allow-empty", action="store_true",
                   help="确认解完会变空 commit（极少用，通常该走 drop）")
    p.add_argument("--add", action="append", default=[],
                   help="要一并带上的新建文件（可重复）；不报备的 untracked 会被拒绝")

    p = rv.add_parser("drop", help="确认上游已吸收，让这个 patch 退役")
    p.add_argument("--reason", required=True)

    p = rv.add_parser("stop", help="解不动，交给人；本任务到此为止")
    p.add_argument("--reason", required=True)

    rv.add_parser("finish", help="体检 + 落候选分支")
    rv.add_parser("abort", help="放弃本轮，树回到干净状态")

    rs.set_defaults(func=cmd_resolve)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
