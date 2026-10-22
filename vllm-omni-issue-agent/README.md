# vllm-omni-issue-agent

每天下午扫一遍 [vllm-project/vllm-omni](https://github.com/vllm-project/vllm-omni/issues)
新开的 bug，筛出**还没人认领**的，让 Claude 判断哪些值得修、在 H20 上能不能复现、要几张卡。
挑中了再手动让它修：拉本地分支、起 GPU pod 占卡、复现、修、写回归测试。

**只到本地分支为止**：不推送、不在 GitHub 上评论 / 认领 / 开 PR。上游的
[AI Usage Policy](https://github.com/vllm-project/vllm-omni/blob/main/docs/contributing/README.md#ai-usage-policy)
要求 PR 作者本人回答 contributor intent gate、披露 AI 使用，非 committer 最多 5 个未合 PR —— 提不提是人的决定。

## 两种模式

| | 每日分诊（`run.sh`） | 修复（`run.sh --fix <号>`） |
|---|---|---|
| 谁触发 | launchd，每天 15:00 | 你手动 |
| 机械部分 | `agent.py scan`：搜 issue → 读 timeline 判认领 | `agent.py fix start`：开分支 + 隔离 worktree |
| Claude 做什么 | 读全文、去代码里找落点、`triage add` 下结论 | 起 pod 占卡 → 装环境拉模型 → 复现 → 修 → 测 → 本地提交 |
| GPU | 不碰 | 最多 `max_cards`（4）张，跑完删 pod |
| 产物 | `reports/<日期>.md` + 通知 | 本地分支 `issue-fix/<号>-<slug>` + `reports/fix-<号>.md` + 通知 |

```bash
vllm-omni-issue-agent/run.sh                         # 分诊（launchd 调的就是这条）
vllm-omni-issue-agent/run.sh --fix 9242              # 修；卡数按分诊结论，没有就 1
vllm-omni-issue-agent/run.sh --fix 9242 --cards 2
vllm-omni-issue-agent/run.sh --fix 9242 --keep-pod   # 修完放卡但留着 pod，接着手工调
python3 vllm-omni-issue-agent/agent.py status
```

修好的分支在主仓库里就能看到（worktree 共享 ref）：

```bash
git -C ~/Projects/workspaces/vllm-omni-ant log --oneline origin/main..issue-fix/9242-xxx
cd ~/.cache/vllm-omni-issue-agent/issue-9242        # 接着改
```

## 怎么判断"没人认领"

扫描条件：近 21 天新开、open、无 assignee、没有用 closing 关键字关联的 PR，带 `bug` 标签
或标题有 `[Bug]`。然后逐个读 timeline：

| 状态 | 依据 |
|---|---|
| 已有人在做 | 上游有 **open** 的 PR 提到它 / 已关联 PR / 14 天内有人留言认领（"I'll take this"、`/assign`、"我来修"…） |
| 可能已修 | 上游有**已合入**的 PR 提到它，issue 还开着 |
| 认领已过期 | 有人认领过，但超过 14 天没 PR |
| 未认领 | 以上都没有 |

下游 fork / 别的项目的 PR 提到它不算认领。正文里作者自己说要提 PR 的，扫描不查，交给 Claude 读全文时判断。
未认证的 GitHub API 每小时 60 次，timeline 每轮最多读 30 个；扫描顺手把每个 issue 的全文和评论落到
`state/issues/<号>.md`，分诊直接读，不再逐个调 API。想放开限制就放一个只读 token 到
`~/.config/personal-agents/github.env`（所有 agent 共用，由 `scripts/_env.sh` 加载，坏 token 会自动弃用）。

## 首次配置（集群细节只在本机）

本仓库是公开的，镜像 / 节点 / NAS / namespace 不进仓库，放 `~/.config/vllm-omni-issue-agent/`：

```bash
mkdir -p ~/.config/vllm-omni-issue-agent && chmod 700 ~/.config/vllm-omni-issue-agent
$EDITOR ~/.config/vllm-omni-issue-agent/pod.json        # 格式见下
python3 vllm-omni-issue-agent/agent.py pod template --from <一个能用的调试 mds/Model 名>
```

```json
{
  "namespace": "<ns>",
  "image": "<registry>/vllm-omni:<tag>",
  "nodes": ["<节点名>", "..."],
  "gpu_key": "nvidia.com/H20",
  "resources": {"cpu": "32", "memory": "256Gi", "ephemeral-storage": "400Gi"},
  "free_mem_mib": 1024,
  "work_dir": "<NAS 上的工作目录>",
  "hf_home": "<NAS 上的 HF 缓存>",
  "hf_endpoint": "https://hf-mirror.com",
  "name_prefix": "debug-omni-issue"
}
```

`pod template` 从参考对象派生 `mds.json` / `model.json`，去掉宿主机 `/home` 挂载、
serviceEntry 和 preStop，参考对象之后被删了也不影响。镜像 tag 会下线，换镜像只改 `image`。

## 装 / 改 / 停定时

```bash
scripts/install-schedule.sh vllm-omni-issue-agent --at 15:00
scripts/install-schedule.sh vllm-omni-issue-agent --status
scripts/install-schedule.sh vllm-omni-issue-agent --uninstall
launchctl kickstart -p gui/$(id -u)/local.vllm-omni-issue-agent    # 立即试跑分诊
```

launchd 按**系统本地时区**触发，机器换时区后要重新确认。

## 架构

```
run.sh                         环境 + 降级兜底 + 修复结束必删 pod（trap）
 ├─ agent.py scan / render / triage / notify       分诊的机械部分
 │    pipeline/gh.py             GitHub 只读查询 + 认领判断（HTTP 借 ai-infra-agent/pipeline/http.py）
 │    pipeline/scan.py           搜 + 读 timeline → state/candidates.json
 │    pipeline/triage.py         Claude 的结论落盘（带校验）→ state/triage.json
 │    pipeline/report.py         渲染报告，保留 Claude 写的分析
 ├─ agent.py fix …              pipeline/fix.py：分支 / worktree / 带闸门的提交
 ├─ agent.py pod …              pipeline/pod.py：建删 pod、挑卡占卡、同步代码、后台命令
 │    pipeline/pod_helper.py     拷进 pod 里跑：占卡进程、后台 runner、日志
 └─ claude + .claude/skills/vllm-omni-issue.md     判断部分
```

## 占卡是怎么做的

pod 走借卡模式（card-num 0）：调度器不知道我们用哪几张卡，别人判断空闲也只看显存。所以：

1. `pod up` 建好 pod 后用 `nvidia-smi` 实测，挑显存 < 1GiB 的卡，**立刻**起一个 torch
   进程把这几张卡的显存占满（留 1.5GiB 余量）。实际占到不足 85% 的说明刚被别人抢了一部分，换卡重来。
2. 拉模型、装环境、Claude 读代码想方案的时候都占着。
3. `pod run --gpu` 跑 GPU 命令前放掉，命令一结束马上占回来（先占回再报告结束，下一条命令不会和它抢）。
4. run.sh 收尾删 pod（看门狗 kill、Ctrl-C 也会走 trap）；`--keep-pod` 时只放卡不删。

## 七个反直觉的坑（改代码前先看）

1. **kubectl 不能带代理变量**。`_env.sh` 设了 `HTTPS_PROXY`（claude 要），而 apiserver 在
   一个不在 `NO_PROXY` 里的内网域名下 —— 带着就绕去本地 Clash。`pod._kube_env()` 一律剥掉。
2. **`--request-timeout` 对 exec 是整条流的时限**。给 exec 加 60s 会把占卡（torch 初始化 4 张卡要几十秒）
   和同步掐断。exec 只用进程超时兜底，其它 kubectl 照 skill 加 60s。
3. **长命令不能挂在 exec 上**。apiserver 抖，一条 exec 挂十分钟迟早断。所有长命令在 pod 里后台跑、
   日志落 NAS，Mac 这边短轮询；runner 按 id 幂等，exec 断了重试不会起第二份。
4. **占卡进程要走 login shell**。节点驱动（实测 R550 / R570）低于镜像要的 R580，forward-compat 库路径是 profile 里设的；
   直接起 python，torch 会报驱动太旧。
5. **`CUDA_VISIBLE_DEVICES` 用卡号不用 UUID**，并设 `CUDA_DEVICE_ORDER=PCI_BUS_ID`。vLLM 的
   custom all-reduce 会对它做 `int()`；不设顺序的话 CUDA 的编号和 nvidia-smi 对不上。
6. **同步代码不用先提交**。`pod sync` 用临时 index 给 worktree 当前内容（含没提交的改动和新文件）
   拍快照 commit，打 bundle 传进 pod 里的 clone。`pod run` 默认先同步一次 —— 改完忘了同步，
   就会拿旧代码测出错误结论。

7. **timeline 不能带 token**。fine-grained token 读别人的公开仓库时没有 pull_requests 权限，
   timeline 会静默丢掉 PR 的 cross-referenced 事件（#8503：带 token 10 条、匿名 17 条）——
   有人在修的 issue 全被当成未认领。`gh.timeline()` 一律匿名请求；搜索、issue 正文照常带 token。

## 安全边界

- 不往 GitHub 发任何东西；提交只在本地分支，`fix commit` 自动 `-s`、拒绝 AI 署名 / 冲突标记 / 没报备的新文件。
- 不碰主 checkout：分支和 worktree 在 `~/.cache/vllm-omni-issue-agent/issue-<号>/`，分诊只读 `origin/main`。
- pod 对象都带 `personal-agents/owner: vllm-omni-issue-agent` 注解，删除前回查，不是自己的拒绝删除。
- 卡数上限写在 `config/agent.json`（`max_cards: 4`），`pod up` 超了直接拒绝。
- 两个 `--fix` 不能同时跑（`state/fix.json` 记着占用者）。
