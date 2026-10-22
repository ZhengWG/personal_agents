"""GPU pod 生命周期：建 → 挑空卡占住 → 同步代码 / 准备环境 / 跑命令 → 删。

做法照 gpu-debug-pod skill：Model + ModelDeployStrategy 一对，借卡模式（card-num 0），
按显存实测挑空卡。skill 里"apply / delete 前要用户确认"这一步，由用户手动敲
`run.sh --fix` 代替；其余规矩写死在这里：

1. **只删自己建的**。每个对象都打 OWNER 注解，删除前回查，不是自己的一律拒绝。
2. **从 up 到 down 全程占卡**。借卡模式下调度器看不见我们，别人判断空闲只看显存，
   拉模型、装环境的几十分钟里不占住，卡就被借走了。只在跑 GPU 命令的那一段放掉。
3. **卡数有上限**（config 的 max_cards），超了直接拒绝。
4. 集群细节（镜像 / 节点 / NAS / namespace / pod 模板）只在本机的
   ~/.config/vllm-omni-issue-agent/，本仓库是公开的。
"""
import datetime
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time

from . import paths

OWNER_KEY = "personal-agents/owner"
OWNER = "vllm-omni-issue-agent"
HELPER_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pod_helper.py")
POD_HOME = "/tmp/omni-issue"
HELPER = POD_HOME + "/helper.py"
CONTAINER = "main"
# 实际占到的显存低于这个比例 = 挑卡和占卡之间被别人抢了一部分，换一张
HELD_RATIO = 0.85
# 其余错误（NotFound / Forbidden / webhook 拒绝）重试也没用
_TRANSIENT = ("Unable to connect", "i/o timeout", "TLS handshake", "connection refused",
              "connection reset", "EOF", "context deadline exceeded", "Client.Timeout",
              "etcdserver", "the server is currently unable", "timed out", "Internal error")


class PodError(RuntimeError):
    pass


def _kube_env():
    # apiserver 的内网域名不在 _env.sh 的 NO_PROXY 里；带着代理变量 kubectl
    # 会绕去本地 Clash。kubectl 一律直连。
    env = dict(os.environ)
    for key in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
        env.pop(key, None)
    return env


def _kc(args, data=None, timeout=180):
    """跑一条 kubectl，返回 (rc, stdout, stderr)。超时记为 rc=124。"""
    if isinstance(data, str):
        data = data.encode()
    # --request-timeout 对 exec 是整条流的时限，会把跑得久的 hold / sync 掐断；
    # exec 只靠下面的进程超时兜底。
    flags = [] if "exec" in args[:4] else ["--request-timeout=60s"]
    try:
        proc = subprocess.run(["kubectl"] + flags + list(args), input=data,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout, env=_kube_env())
    except subprocess.TimeoutExpired:
        return 124, "", "timed out after %ds" % timeout
    return (proc.returncode, proc.stdout.decode(errors="replace"),
            proc.stderr.decode(errors="replace"))


def kubectl(args, data=None, retries=3, timeout=180):
    """失败就抛 —— 超时返回的是空输出，绝不能把空结果当"不存在"往下走。"""
    err = ""
    for attempt in range(1, retries + 1):
        rc, out, err = _kc(args, data, timeout)
        if rc == 0:
            return out
        if attempt < retries and (rc == 124 or any(s in err for s in _TRANSIENT)):
            time.sleep(3 * attempt)
            continue
        break
    raise PodError("kubectl %s 失败：%s" % (" ".join(args[:4]), err.strip()[-800:]))


def _not_found(args):
    rc, out, err = _kc(args)
    if rc == 0:
        return False, out
    if "NotFound" in err or "not found" in err:
        return True, ""
    raise PodError("kubectl %s 失败：%s" % (" ".join(args[:4]), err.strip()[-800:]))


def _quiet(text):
    # 镜像的 login profile 每次都打两行 forward-compat 提示，混在输出里只是噪音
    return "\n".join(ln for ln in text.splitlines() if not ln.startswith("[cuda-compat]"))


def _last_json(text):
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    raise PodError("helper 没有返回 JSON：%s" % text.strip()[-500:])


# ---------------------------------------------------------------- 模板 ----

def make_template(cfg, local, ref):
    """从一个能用的调试对象派生模板，存到本机配置目录。只在换参考对象时跑一次。"""
    ns = local["namespace"]
    mds = json.loads(kubectl(["get", "mds", ref, "-o", "json"]))
    model = json.loads(kubectl(["-n", ns, "get", "model", ref, "-o", "json"]))

    role = mds["spec"]["roles"][0]
    role["replicas"] = 1
    # 参考对象自带的服务注册对调试 pod 没用，还可能把它挂进服务发现
    role.pop("serviceEntry", None)
    spec = role["podTemplate"]["spec"]
    container = spec["containers"][0]
    container.pop("lifecycle", None)          # preStop 调的是 modelserver，这里没有
    # 整个宿主机 /home 读写挂进来对自动化 agent 是多余的风险
    dropped = {v["name"] for v in spec.get("volumes", [])
               if (v.get("hostPath") or {}).get("path") == "/home"}
    spec["volumes"] = [v for v in spec.get("volumes", []) if v["name"] not in dropped]
    container["volumeMounts"] = [m for m in container.get("volumeMounts", [])
                                 if m["name"] not in dropped]
    mds_tpl = {"apiVersion": mds["apiVersion"], "kind": mds["kind"],
               "metadata": {"labels": mds["metadata"].get("labels", {})},
               "spec": dict(mds["spec"], roles=[role])}

    labels = dict(model["metadata"].get("labels", {}))
    # 和 spec.model 配套删：不挂权重就一起不要（skill 第 4 步）
    for key in ("model.infernex.io/cluster-name", "model.infernex.io/hmr-volume-loader"):
        labels.pop(key, None)
    mspec = dict(model["spec"])
    mspec.pop("model", None)
    model_tpl = {"apiVersion": model["apiVersion"], "kind": model["kind"],
                 "metadata": {"labels": labels}, "spec": mspec}

    os.makedirs(cfg["local_config_dir"], exist_ok=True)
    for name, obj in (("mds.json", mds_tpl), ("model.json", model_tpl)):
        with open(paths.local_file(cfg, name), "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2, ensure_ascii=False)
    return {"from": ref, "dropped_volumes": sorted(dropped),
            "files": [paths.local_file(cfg, "mds.json"), paths.local_file(cfg, "model.json")]}


def build(cfg, local, name, node):
    with open(paths.local_file(cfg, "mds.json"), encoding="utf-8") as fh:
        mds = json.load(fh)
    with open(paths.local_file(cfg, "model.json"), encoding="utf-8") as fh:
        model = json.load(fh)
    owner = {OWNER_KEY: OWNER}

    mds["metadata"] = {"name": name, "labels": mds["metadata"].get("labels", {}),
                       "annotations": owner}
    tpl = mds["spec"]["roles"][0]["podTemplate"]
    tpl["metadata"]["labels"]["model.infernex.io/card-num"] = "0"
    tpl["spec"]["nodeName"] = node
    c = tpl["spec"]["containers"][0]
    c["image"] = local["image"]
    c["command"] = ["sh", "-c", "sleep inf"]
    res = dict(local["resources"], **{local["gpu_key"]: "0"})
    c["resources"] = {"requests": dict(res), "limits": dict(res)}
    # 借卡不在 pod 级钉 UUID：要先进去看哪几张空着才知道，卡号写进进程的环境变量
    c["env"] = [e for e in c.get("env", []) if "VISIBLE_DEVICES" not in e["name"]]

    labels = dict(model["metadata"].get("labels", {}))
    for key in ("modeldeploystrategy", "service-id", "service-name"):
        labels["model.infernex.io/" + key] = name
    model["metadata"] = {"name": name, "namespace": local["namespace"], "labels": labels,
                         "annotations": owner}
    model["spec"]["modelDeployStrategyName"] = name
    return mds, model


# ---------------------------------------------------------------- 建 / 删 ----

def _name(local, node):
    tail = node.split(".")[0][-3:]
    return "%s-%s-%s" % (local.get("name_prefix", "debug-omni-issue"),
                         datetime.datetime.now().strftime("%m%d-%H%M"), tail)


def _create(cfg, local, name, node):
    ns = local["namespace"]
    mds, model = build(cfg, local, name, node)
    kubectl(["apply", "--dry-run=server", "-f", "-"], json.dumps(mds))
    kubectl(["apply", "-f", "-"], json.dumps(mds))          # 先 mds 后 Model，反了找不到模板
    kubectl(["-n", ns, "apply", "--dry-run=server", "-f", "-"], json.dumps(model))
    kubectl(["-n", ns, "apply", "-f", "-"], json.dumps(model))


_BAD_WAIT = ("ImagePullBackOff", "ErrImagePull", "CrashLoopBackOff", "CreateContainerConfigError",
             "InvalidImageName")


def _wait_running(local, name, timeout=900):
    ns = local["namespace"]
    sel = "model.infernex.io/modeldeploystrategy=%s" % name
    start = time.time()
    while time.time() - start < timeout:
        pods = json.loads(kubectl(["-n", ns, "get", "pods", "-l", sel, "-o", "json"]))["items"]
        for p in pods:
            if p["status"].get("phase") == "Running":
                return p["metadata"]["name"]       # 0/1 Running 是预期（sleep inf，探针恒失败）
            for cs in p["status"].get("containerStatuses", []):
                reason = ((cs.get("state") or {}).get("waiting") or {}).get("reason")
                if reason in _BAD_WAIT and time.time() - start > 120:
                    raise PodError("pod %s 卡在 %s" % (p["metadata"]["name"], reason))
        if not pods and time.time() - start > 120:
            # Pod 没建出来时错误只在 ModelInstance 的 event 上（skill 第 5 步）
            _, ev, _ = _kc(["-n", ns, "get", "events", "--sort-by=.lastTimestamp"])
            hits = [ln for ln in ev.splitlines() if name in ln][-5:]
            if hits:
                print("[pod] %s 还没有 pod，相关 event：\n  %s" % (name, "\n  ".join(hits)),
                      file=sys.stderr)
        time.sleep(10)
    raise PodError("%s 等了 %ds 还没 Running" % (name, timeout))


def _delete(local, name):
    ns = local["namespace"]
    for args in (["-n", ns, "get", "model", name, "-o", "json"],
                 ["get", "mds", name, "-o", "json"]):
        missing, out = _not_found(args)
        if missing:
            continue
        ann = json.loads(out)["metadata"].get("annotations") or {}
        if ann.get(OWNER_KEY) != OWNER:
            raise PodError("%s %s 不是本 agent 建的（没有 %s 注解），拒绝删除"
                           % (args[-4], name, OWNER_KEY))
    # 删 Model 级联删 ModelInstance 和 Pod；mds 是集群级的，不吃 -n
    _kc(["-n", ns, "delete", "model", name, "--wait=false", "--ignore-not-found"])
    sel = "model.infernex.io/modeldeploystrategy=%s" % name
    deadline = time.time() + 300
    while time.time() < deadline:
        items = json.loads(kubectl(["-n", ns, "get", "pods", "-l", sel, "-o", "json"]))["items"]
        if not items:
            break
        time.sleep(10)
    else:
        raise PodError("%s 的 pod 5 分钟还没删干净，手动看：kubectl -n %s get pods -l %s"
                       % (name, ns, sel))
    kubectl(["delete", "mds", name, "--ignore-not-found"])


def ours(local):
    """集群里所有带本 agent 注解的 mds 名字。"""
    items = json.loads(kubectl(["get", "mds", "-o", "json"], timeout=300))["items"]
    return sorted(i["metadata"]["name"] for i in items
                  if (i["metadata"].get("annotations") or {}).get(OWNER_KEY) == OWNER)


# ---------------------------------------------------------------- pod 内操作 ----

def _exec(st, argv, data=None, retries=1, timeout=300):
    return kubectl(["-n", st["namespace"], "exec", "-i" if data is not None else "-q",
                    st["pod"], "-c", CONTAINER, "--"] + argv, data, retries, timeout)


def helper(st, args, retries=3, timeout=300):
    # helper 的每个动作都是幂等的（run 按 id 去重），断了可以放心重试
    return _last_json(_exec(st, ["python3", HELPER] + args, retries=retries, timeout=timeout))


def _upload(st, path, data):
    _exec(st, ["sh", "-c", "mkdir -p %s && cat > %s" % (POD_HOME, path)], data=data, retries=3)


def _write_env(st, local, devices):
    env = {
        # 和 nvidia-smi 的编号对齐；默认的 FASTEST_FIRST 会让编号对不上
        "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
        # 用卡号不用 UUID：vLLM 的 custom all-reduce 会对它做 int()
        "CUDA_VISIBLE_DEVICES": ",".join(str(d) for d in devices),
        "HF_HOME": local["hf_home"],
        "HF_ENDPOINT": local["hf_endpoint"],
        "HF_HUB_DISABLE_PROGRESS_BARS": "1",
        "OMNI_WORK": local["work_dir"],
        "OMNI_REPO": local["work_dir"].rstrip("/") + "/vllm-omni",
        "OMNI_RUNS": local["work_dir"].rstrip("/") + "/runs",
    }
    _upload(st, POD_HOME + "/env.json", json.dumps(env))
    sh = "".join("export %s=%s\n" % (k, shlex.quote(v)) for k, v in env.items())
    _upload(st, POD_HOME + "/env.sh", sh)


def _ensure_helper(st):
    with open(HELPER_SRC, "rb") as fh:
        _upload(st, HELPER, fh.read())


def _pick_and_hold(st, local, n):
    if n == 0:
        _write_env(st, local, [])
        return []
    bad = set()
    for _ in range(3):
        rows = helper(st, ["gpus"])["gpus"]
        free = [r["index"] for r in rows
                if r["used_mib"] < local.get("free_mem_mib", 1024) and r["index"] not in bad]
        if len(free) < n:
            return None
        pick = free[:n]
        _write_env(st, local, pick)
        info = helper(st, ["hold"], timeout=400)
        if info.get("state") != "holding":
            raise PodError("占卡失败：%s" % info.get("log", info))
        short = [int(k) for k, v in info["held"].items()
                 if v["held_mib"] < HELD_RATIO * v["total_mib"]]
        if not short:
            return pick
        print("[pod] 卡 %s 在挑完之后被别人用了一部分，换卡重来" % short, file=sys.stderr)
        bad.update(short)
        helper(st, ["release"])
    return None


def _running(local, st):
    if not st or not st.get("pod"):
        return False
    missing, out = _not_found(["-n", local["namespace"], "get", "pod", st["pod"], "-o", "json"])
    return not missing and json.loads(out)["status"].get("phase") == "Running"


def up(cfg, local, cards, node=None):
    if not 0 <= cards <= cfg["max_cards"]:
        raise PodError("--cards %d 超出上限 0..%d（config/agent.json 的 max_cards）"
                       % (cards, cfg["max_cards"]))
    st = paths.load(paths.POD)
    if _running(local, st):
        _ensure_helper(st)
        state = helper(st, ["status"])
        if st.get("cards") == cards and (state["holding"] or cards == 0):
            return dict(st, reused=True)
        helper(st, ["release"])
        picked = _pick_and_hold(st, local, cards)
        if picked is None:
            raise PodError("%s 上凑不出 %d 张空卡；pod down 之后 pod up --node 换个节点"
                           % (st["node"], cards))
        st.update(cards=cards, gpus=picked, kept=False)
        paths.save(paths.POD, st)
        return dict(st, reused=True)
    if st:
        # 记录在案但 pod 已经不在了（被驱逐 / 节点重启）：对象先删干净再建新的
        _safe_down(local, st)

    errors = []
    for nd in ([node] if node else local["nodes"]):
        name = _name(local, nd)
        st = {"name": name, "namespace": local["namespace"], "node": nd, "cards": cards,
              "image": local["image"], "created": datetime.datetime.now().isoformat(timespec="seconds")}
        try:
            _create(cfg, local, name, nd)
            paths.save(paths.POD, st)                 # 先落盘：后面任何一步失败都能被 down 找到
            st["pod"] = _wait_running(local, name)
            paths.save(paths.POD, st)
            _ensure_helper(st)
            picked = _pick_and_hold(st, local, cards)
        except PodError as exc:
            errors.append("%s：%s" % (nd, exc))
            _safe_down(local, st)
            continue
        if picked is None:
            errors.append("%s：空卡不足 %d 张" % (nd, cards))
            _safe_down(local, st)
            continue
        st["gpus"] = picked
        paths.save(paths.POD, st)
        return st
    raise PodError("所有候选节点都没成：\n  " + "\n  ".join(errors))


def _safe_down(local, st):
    try:
        _delete(local, st["name"])
    except PodError as exc:
        print("[pod] 清理 %s 失败：%s" % (st["name"], exc), file=sys.stderr)
    if paths.load(paths.POD).get("name") == st["name"]:
        os.remove(paths.POD)


def require(local):
    st = paths.load(paths.POD)
    if not _running(local, st):
        raise PodError("没有在跑的 pod（先 agent.py pod up --cards N）")
    return st


def down(local, keep=False):
    st = paths.load(paths.POD)
    if not st:
        return {"state": "none"}
    if keep:
        # 留 pod 给人接着用，但不能一直占着卡
        if _running(local, st):
            helper(st, ["release"])
        st["kept"] = True
        paths.save(paths.POD, st)
        return {"state": "kept", "name": st["name"], "pod": st.get("pod"),
                "delete": "vllm-omni-issue-agent/agent.py pod down"}
    if _running(local, st):
        try:
            helper(st, ["release"], retries=1)
        except PodError:
            pass                                      # 删 pod 本身就会释放显存
    _delete(local, st["name"])
    os.remove(paths.POD)
    return {"state": "deleted", "name": st["name"]}


def down_stale(local):
    """删掉上一轮崩溃留下的、本 agent 建的对象；当前记录在案的那个留给 up 复用。"""
    keep = paths.load(paths.POD).get("name")
    removed = []
    for name in ours(local):
        if name != keep:
            _delete(local, name)
            removed.append(name)
    return removed


# ---------------------------------------------------------------- 代码 / 环境 / 命令 ----

def _git(args, cwd, env=None):
    proc = subprocess.run(["git"] + args, cwd=cwd, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True)
    if proc.returncode != 0:
        raise PodError("git %s 失败：%s" % (" ".join(args[:3]), proc.stdout.strip()[-500:]))
    return proc.stdout.strip()


def _sh(st, script, timeout=600):
    return _quiet(_exec(st, ["bash", "-lc", "source %s/env.sh && %s" % (POD_HOME, script)],
                        timeout=timeout))


def sync(cfg, st, fix):
    """把 worktree 当前的样子（含没提交的改动和新文件）原样搬进 pod 里的仓库。

    用临时 index 拍一个快照 commit，不碰 worktree 自己的 index；再打成 bundle 传过去。
    这样 Claude 改一行就能测一行，不用为了测试先提交。
    """
    wt = fix["worktree"]
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(tmp, "index"))
        _git(["read-tree", "HEAD"], wt, env)
        _git(["add", "-A"], wt, env)
        tree = _git(["write-tree"], wt, env)
        snap = _git(["commit-tree", tree, "-p", "HEAD", "-m", "omni-issue sync snapshot"], wt)
        _git(["update-ref", "refs/omni-issue/sync", snap], wt)
        bundle = os.path.join(tmp, "sync.bundle")
        _git(["bundle", "create", "-q", bundle, "refs/omni-issue/sync", "^" + fix["base"]], wt)
        # worktree 和主仓库共用 ref，打完包就删，别在用户仓库里留东西
        _git(["update-ref", "-d", "refs/omni-issue/sync"], wt)
        with open(bundle, "rb") as fh:
            data = fh.read()

    url = "https://github.com/%s.git" % cfg["upstream"]
    _sh(st, 'mkdir -p "$OMNI_WORK" "$OMNI_RUNS" && cd "$OMNI_WORK" && '
            '{ [ -d vllm-omni/.git ] || git clone -q --filter=blob:none %s vllm-omni; } && '
            'cd vllm-omni && git fetch -q origin main && '
            '{ git cat-file -e %s^{commit} 2>/dev/null || git fetch -q origin %s; }'
            % (url, fix["base"], fix["base"]), timeout=900)
    _upload(st, POD_HOME + "/sync.bundle", data)
    head = _sh(st, 'cd "$OMNI_REPO" && '
                   'git fetch -q -f %s/sync.bundle refs/omni-issue/sync:refs/omni-issue/sync && '
                   'git checkout -q -f --detach refs/omni-issue/sync && git clean -fdq && '
                   'git log -1 --format="%%h %%s" && git diff --stat %s HEAD | tail -1'
                   % (POD_HOME, fix["base"]))
    return {"snapshot": snap[:10], "pod_head": head.strip()}


PREP = r"""set -eo pipefail
pin=$(sed -n 's/^ARG VLLM_VERSION=\([0-9][0-9.]*\).*/\1/p' docker/Dockerfile.ci | head -1)
have=$(python3 -c 'import vllm; print(vllm.__version__)' 2>/dev/null || echo none)
echo "[prep] 上游 main 锁定 vllm ${pin:-?}，镜像里是 ${have}"
if [ -n "$pin" ] && [ "${have%%+*}" != "$pin" ]; then pip install "vllm==$pin"; fi
pip install -e .
for m in @MODELS@; do
  echo "[prep] 下载 $m 到 $HF_HOME"
  if command -v hf >/dev/null; then hf download "$m"; else huggingface-cli download "$m"; fi
done
python3 -c 'import vllm, vllm_omni; print("[prep] vllm", vllm.__version__, "| vllm_omni", vllm_omni.__file__)'
"""


def prep_command(models):
    return PREP.replace("@MODELS@", " ".join(shlex.quote(m) for m in models))


def run(st, command, gpu=False, run_id=None):
    run_id = run_id or datetime.datetime.now().strftime("%m%d-%H%M%S")
    args = ["run", run_id, "--cmd", command] + (["--gpu"] if gpu else [])
    helper(st, args)
    return run_id


def wait(st, run_id, budget, tail_lines=150):
    """短轮询到结束或 budget 用完。返回 (state, rc)；没跑完 rc=None。"""
    deadline = time.time() + budget
    last = {}
    while True:
        last = helper(st, ["poll", run_id])
        if last["state"] in ("done", "lost", "unknown") or time.time() >= deadline:
            break
        time.sleep(min(15, max(1, deadline - time.time())))
    print(log(st, run_id, tail_lines))
    return last["state"], last.get("rc")


def log(st, run_id, lines=150, grep=None):
    args = ["python3", HELPER, "tail", run_id, "-n", str(lines)] + (["--grep", grep] if grep else [])
    rc, out, err = _kc(["-n", st["namespace"], "exec", "-q", st["pod"], "-c", CONTAINER, "--"] + args)
    return _quiet(out or err)


def shell(st, command, timeout=300):
    """同步跑一条短命令（不放卡）。长命令用 run，exec 挂久了会被 apiserver 掐断。"""
    rc, out, err = _kc(["-n", st["namespace"], "exec", "-q", st["pod"], "-c", CONTAINER, "--",
                        "bash", "-lc", 'source %s/env.sh && { cd "$OMNI_REPO" 2>/dev/null || '
                        'cd "$OMNI_WORK"; } && %s' % (POD_HOME, command)], timeout=timeout)
    return rc, _quiet(out + err)
