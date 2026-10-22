#!/usr/bin/env python3
"""在 GPU pod 里跑的小助手：占卡 / 放卡 / 后台跑命令 / 查进度。

agent.py 把它拷进 pod 的 /tmp/omni-issue/，每次用一条短的 kubectl exec 调它。
长命令一律在 pod 里后台跑、日志落 NAS，Mac 那边只做短轮询 —— 这个集群的
apiserver 抖得厉害，一条 exec 挂十分钟迟早会断，断了不能把正在跑的测试带走。

占卡的原理：这些 pod 走借卡模式（card-num 0），调度器不知道我们在用哪几张卡，
别人判断空闲也只看显存。所以从拉模型、装环境到跑测试的整个过程，都要有个进程
把选中的卡显存占住；跑 GPU 命令前放掉、跑完立刻再占回来。
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time

HOME = "/tmp/omni-issue"
ENV_JSON = os.path.join(HOME, "env.json")
ENV_SH = os.path.join(HOME, "env.sh")
HOLD_PID = os.path.join(HOME, "holder.pid")
HOLD_INFO = os.path.join(HOME, "held.json")
HOLD_LOG = os.path.join(HOME, "holder.log")
# 每张卡留一点余量：CUDA context 本身要几百 MiB，占到 100% 反而会让 holder 自己 OOM
RESERVE_MIB = 1536


def _env():
    env = dict(os.environ)
    with open(ENV_JSON) as fh:
        env.update(json.load(fh))
    return env


def _read_pid(path):
    try:
        with open(path) as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def _alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    # 僵尸进程 kill(0) 也成功，看一眼状态
    try:
        with open("/proc/%d/stat" % pid) as fh:
            return fh.read().split()[2] != "Z"
    except OSError:
        return False


def _emit(obj):
    print(json.dumps(obj, ensure_ascii=False))


# ---------------------------------------------------------------- 占卡 ----

def _holder():
    import torch

    devices = os.environ.get("CUDA_VISIBLE_DEVICES", "").split(",")
    blocks, held = [], {}
    for i in range(torch.cuda.device_count()):
        free, total = torch.cuda.mem_get_info(i)
        n = max(free - RESERVE_MIB * 2 ** 20, 0)
        blocks.append(torch.empty(n, dtype=torch.uint8, device="cuda:%d" % i))
        held[devices[i] if i < len(devices) else str(i)] = {
            "held_mib": n >> 20, "total_mib": total >> 20}
    tmp = HOLD_INFO + ".tmp"
    with open(tmp, "w") as fh:
        json.dump({"pid": os.getpid(), "held": held, "at": time.strftime("%H:%M:%S")}, fh)
    os.replace(tmp, HOLD_INFO)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    while True:
        time.sleep(3600)


def hold(quiet=False):
    pid = _read_pid(HOLD_PID)
    if _alive(pid) and os.path.exists(HOLD_INFO):
        with open(HOLD_INFO) as fh:
            info = json.load(fh)
        if not quiet:
            _emit(dict(info, state="holding"))
        return 0
    if not _env().get("CUDA_VISIBLE_DEVICES"):
        if not quiet:
            _emit({"state": "no-gpu"})
        return 0
    for path in (HOLD_INFO, HOLD_PID):
        if os.path.exists(path):
            os.remove(path)
    # 走 login shell：镜像的 CUDA forward-compat 库路径（节点驱动 R550/R570 < 镜像要的 R580）
    # 是 profile 里设的，直接起 python 的话 torch 会报驱动太旧。
    with open(HOLD_LOG, "ab") as log:
        proc = subprocess.Popen(["bash", "-lc", "exec %s %s _holder" % (
                                    sys.executable, os.path.abspath(__file__))],
                                env=_env(), stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)
    with open(HOLD_PID, "w") as fh:
        fh.write(str(proc.pid))
    deadline = time.time() + 180
    while time.time() < deadline:
        if os.path.exists(HOLD_INFO):
            with open(HOLD_INFO) as fh:
                info = json.load(fh)
            if not quiet:
                _emit(dict(info, state="holding"))
            return 0
        if proc.poll() is not None:
            break
        time.sleep(1)
    with open(HOLD_LOG, errors="replace") as fh:
        tail = fh.read()[-2000:]
    if not quiet:
        _emit({"state": "failed", "log": tail})
    return 1


def release(quiet=False):
    pid = _read_pid(HOLD_PID)
    if _alive(pid):
        os.kill(pid, signal.SIGTERM)
        deadline = time.time() + 60
        while _alive(pid) and time.time() < deadline:
            time.sleep(0.5)
        if _alive(pid):
            os.kill(pid, signal.SIGKILL)
            time.sleep(2)
    for path in (HOLD_INFO, HOLD_PID):
        if os.path.exists(path):
            os.remove(path)
    if not quiet:
        _emit({"state": "released"})
    return 0


def status():
    """只看不动：占着没有、占的哪几张。（hold 会顺手把卡占上，查状态不能用它）"""
    holding = _alive(_read_pid(HOLD_PID)) and os.path.exists(HOLD_INFO)
    info = {}
    if holding:
        with open(HOLD_INFO) as fh:
            info = json.load(fh)
    _emit({"holding": holding, "held": info.get("held", {}),
           "cuda_visible_devices": _env().get("CUDA_VISIBLE_DEVICES", "")})
    return 0


# ---------------------------------------------------------------- 后台命令 ----

def _run_paths(run_id):
    runs = _env()["OMNI_RUNS"]
    os.makedirs(runs, exist_ok=True)
    base = os.path.join(runs, run_id)
    return base + ".log", base + ".rc", base + ".pid"


def run(run_id, gpu, command):
    log, rc, pidf = _run_paths(run_id)
    if os.path.exists(pidf):              # 幂等：Mac 那边 exec 超时重试不会起第二份
        _emit({"id": run_id, "log": log, "already": True})
        return 0
    args = [sys.executable, os.path.abspath(__file__), "_runner", run_id, "--cmd", command]
    if gpu:
        args.append("--gpu")
    proc = subprocess.Popen(args, env=_env(), stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)
    with open(pidf, "w") as fh:
        fh.write(str(proc.pid))
    _emit({"id": run_id, "log": log})
    return 0


def _runner(run_id, gpu, command):
    log, rc_path, _ = _run_paths(run_id)
    with open(log, "ab", buffering=0) as fh:
        def note(msg):
            fh.write(("\n[omni-issue %s] %s\n" % (time.strftime("%H:%M:%S"), msg)).encode())

        was_holding = _alive(_read_pid(HOLD_PID))
        if gpu and was_holding:
            release(quiet=True)
            note("已放卡，开始跑")
        script = 'source %s && { cd "$OMNI_REPO" 2>/dev/null || cd "$OMNI_WORK"; } && %s' % (
            ENV_SH, command)
        rc = subprocess.call(["bash", "-lc", script], stdin=subprocess.DEVNULL,
                             stdout=fh, stderr=subprocess.STDOUT)
        # 先占回卡再写 rc：Mac 看到 rc 就会让下一条 GPU 命令开跑，顺序反了会和占卡抢
        if gpu and was_holding:
            note("命令结束 rc=%d，重新占卡：%s" % (rc, "成功" if hold(quiet=True) == 0 else "失败"))
        else:
            note("命令结束 rc=%d" % rc)
    with open(rc_path + ".tmp", "w") as out:
        out.write(str(rc))
    os.replace(rc_path + ".tmp", rc_path)


def poll(run_id):
    log, rc_path, pidf = _run_paths(run_id)
    size = os.path.getsize(log) if os.path.exists(log) else 0
    if os.path.exists(rc_path):
        with open(rc_path) as fh:
            _emit({"id": run_id, "state": "done", "rc": int(fh.read().strip()), "bytes": size})
    elif _alive(_read_pid(pidf)):
        _emit({"id": run_id, "state": "running", "bytes": size})
    elif os.path.exists(pidf):
        _emit({"id": run_id, "state": "lost", "bytes": size})   # runner 被杀了，没留下 rc
    else:
        _emit({"id": run_id, "state": "unknown"})
    return 0


def tail(run_id, lines, grep):
    log, _, _ = _run_paths(run_id)
    if not os.path.exists(log):
        print("(还没有日志：%s)" % log)
        return 1
    if grep:
        return subprocess.call(["grep", "-n", "-E", "-i", "-m", "200", grep, log])
    return subprocess.call(["tail", "-n", str(lines), log])


def gpus():
    out = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=index,uuid,memory.used,memory.total,utilization.gpu",
         "--format=csv,noheader,nounits"], text=True)
    rows = []
    for line in out.strip().splitlines():
        idx, uuid, used, total, util = [x.strip() for x in line.split(",")]
        rows.append({"index": int(idx), "uuid": uuid, "used_mib": int(used),
                     "total_mib": int(total), "util": int(util) if util.isdigit() else None})
    _emit({"gpus": rows})
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="verb", required=True)
    sub.add_parser("hold")
    sub.add_parser("release")
    sub.add_parser("gpus")
    sub.add_parser("status")
    sub.add_parser("_holder")
    for name in ("run", "_runner"):
        p = sub.add_parser(name)
        p.add_argument("id")
        p.add_argument("--gpu", action="store_true")
        p.add_argument("--cmd", dest="command", required=True, help="整条 shell 命令（一个参数）")
    p = sub.add_parser("poll")
    p.add_argument("id")
    p = sub.add_parser("tail")
    p.add_argument("id")
    p.add_argument("-n", type=int, default=150)
    p.add_argument("--grep")
    args = ap.parse_args()

    if args.verb == "hold":
        return hold()
    if args.verb == "release":
        return release()
    if args.verb == "gpus":
        return gpus()
    if args.verb == "status":
        return status()
    if args.verb == "_holder":
        return _holder()
    if args.verb in ("run", "_runner"):
        fn = run if args.verb == "run" else _runner
        return fn(args.id, args.gpu, args.command)
    if args.verb == "poll":
        return poll(args.id)
    if args.verb == "tail":
        return tail(args.id, args.n, args.grep)
    return 2


if __name__ == "__main__":
    sys.exit(main())
