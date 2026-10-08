"""产物验收 —— 一棵演练结果树，凭什么说它是对的。

"rebase 跑完没报错"不等于结果是对的：静默掉 patch、解冲突时留下 <<<<<<<、
把文件改成语法错误，这三种都不会让 git 返回非 0。所以每一轮都要独立验收。

验收结果也是**推送的唯一闸门**（见 tasks.maybe_push）：宁可今天不推，
也不要把一棵带冲突标记或编译不过的树推到 ant remote 上。
"""
import os

from . import gitutil as g


def _check(name, ok, detail=""):
    return {"name": name, "ok": bool(ok), "detail": detail[:500]}


def _changed_files(wt, base, head="HEAD"):
    text = g.out(["diff", "--name-only", "%s..%s" % (base, head)], wt)
    return [p for p in text.splitlines() if p.strip()]


def verify(entry, wt, syntax_files=None):
    """给一个已经跑完的 task 结果做体检，写回 entry['checks'] / entry['verified']。

    `syntax_files` 是要做语法检查的文件（相对 worktree）。**只传解冲突时动过的文件**，
    别传整个 delta：本脚本跑在 /usr/bin/python3（3.9）上，而 vLLM 要求 3.10+，
    拿 3.9 的语法去编译上游正常代码会大片误报 invalid syntax。实测 2240 个文件
    报了两个假阳性，全是 3.10+ 语法。
    """
    checks = []

    marker = g.in_progress(wt)
    checks.append(_check("rebase/merge 已结束", marker is None, marker or ""))

    dirty = g.out(["status", "--porcelain", "--untracked-files=no"], wt)
    checks.append(_check("工作区干净", not dirty, dirty))

    base = entry.get("onto_sha") or entry["onto_ref"]
    try:
        changed = _changed_files(wt, base)
    except g.GitError as exc:
        entry["checks"] = checks + [_check("能算出改动文件", False, str(exc))]
        entry["verified"] = False
        return entry

    # 只扫本轮相对基线动过的文件 —— 全树扫一遍又慢又会误报别人的测试数据。
    markers = []
    for rel in changed:
        full = os.path.join(wt, rel)
        if not os.path.isfile(full):
            continue
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                body = fh.read()
        except OSError:
            continue
        if "\n<<<<<<< " in body or body.startswith("<<<<<<< "):
            markers.append(rel)
    checks.append(_check("无冲突标记残留", not markers, ", ".join(markers)))

    # 用内置 compile() 而不是 py_compile：后者要落一个 .pyc，
    # 指到 /dev/null 会被 Python 以 "non-regular file" 拒绝（实测踩过）。
    # 这里只要语法过关，不需要字节码。
    pys = [r for r in (syntax_files if syntax_files is not None else []) if r.endswith(".py")]
    bad = []
    for rel in pys:
        full = os.path.join(wt, rel)
        if not os.path.isfile(full):
            continue
        try:
            with open(full, "rb") as fh:
                compile(fh.read(), rel, "exec")
        except SyntaxError as exc:
            bad.append("%s:%s %s" % (rel, exc.lineno, exc.msg))
        except (ValueError, OSError) as exc:
            bad.append("%s: %s" % (rel, str(exc)[:160]))
    checks.append(_check("解冲突动过的 .py 可编译（%d 个）" % len(pys), not bad, "; ".join(bad)))

    is_anc = g.git(["merge-base", "--is-ancestor", entry["onto_ref"], "HEAD"],
                   wt, check=False)[0] == 0
    checks.append(_check("产物确实基于 %s" % entry["onto_ref"], is_anc))

    if entry["kind"] == "rebase":
        # 被 `resolve drop` 带着依据主动退役的 patch 是有账可查的决定，不算丢失；
        # 只有静默消失的（missing / radar 里 --empty=stop 拦下但没人处理的）才算。
        missing = entry.get("missing_patches", []) + entry.get("empty_dropped", [])
        checks.append(_check(
            "Ant delta 无丢失（期望 %d 个）" % len(entry.get("expected_patches", [])),
            not missing,
            "; ".join("%s %s" % (c["sha"], c["subject"]) for c in missing)))
        # 没法验证 ≠ 验证通过。查不了就是查不了，一样挡住推送 ——
        # 只是措辞上要和"真的对不上"分开，否则看报告的人会去找不存在的差异。
        align = entry.get("alignment") or {}
        if not align.get("checked"):
            checks.append(_check("delta 对齐（diff-of-diffs）", False,
                                 "本轮无法验证：%s" % align.get("reason", "未执行")))
        else:
            checks.append(_check("delta 对齐（diff-of-diffs）", align.get("aligned"),
                                 "只在 source %d 行 / 只在结果 %d 行" % (
                                     align.get("only_in_source_count", 0),
                                     align.get("only_in_result_count", 0))))

    entry["checks"] = checks
    entry["verified"] = all(c["ok"] for c in checks)
    return entry
