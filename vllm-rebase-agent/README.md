# vllm-rebase-agent

每天把 **Ant delta 演练 rebase 一遍**，在真正要出 release 的那天之前，
就知道哪些 patch 会冲突、哪些会被上游吃掉、哪些会被 git 悄悄丢掉。

盯两个仓库：`vllm-ant`（`Theta/vllm`）和 `vllm-omni-ant`（`Theta/vllm-omni`）。

## 它解决什么问题

`ant/releases/vX.Y.Z` 是「上游 release tag + Ant 私有 patch」。出 release 那天才做
rebase，就会在最赶的时候撞上积攒了几个月的上游重构。更糟的是 **git 会静默丢 patch**：
当一个 patch 的落点（方法、文件）被上游挪走或删掉，3-way merge 之后它变成空 commit，
`git rebase` **不报冲突、不留记录，直接丢掉**（`ant-release-rebase` skill 里 v0.25.0
那次事故就是这么来的）。

这个 agent 每天在**隔离 worktree** 里把同样的动作预演一遍，把这三类问题提前摊开：

| 信号 | 含义 |
|---|---|
| ⚠️ 有冲突 | 照 playbook 能解，但要人动手 |
| 🔴 掉 patch | `--empty=stop` 拦下来的空 patch，或期望回放却没落地的 commit —— **最要紧** |
| 🟠 delta 漂移 | diff-of-diffs 对不上：Ant delta 在新 base 上和在 main 上不是同一份 |

## 两种模式，不互相替代

| | radar（`agent.py run`） | resolve（`agent.py resolve`） |
|---|---|---|
| 遇到冲突 | 记下来 `--skip` 继续 | 停下来，等解完再走 |
| 图什么 | **一轮看全冲突面** | 产出一棵**完整**的候选分支 |
| 谁来跑 | 纯脚本，确定性 | Claude 按 playbook 逐个解 |
| 产物 | 事实报告 | 本地候选分支（**不推送**） |

每天两遍都跑：先 radar 拿全景，再 resolve 逐个解。

**为什么非要有完整的树**：delta 对齐（diff-of-diffs）只有在 rebase 真正跑完时才有意义。
radar 模式下报出来的差异永远被"我主动 skip 掉的那些 patch"占满 —— 实测 vllm-ant 报
「差 11 行」，那 11 行恰好就是被 skip 的那个 patch，等于什么也没验证。同一个仓库
resolve 跑完之后是 **`aligned: true`，773 行全同** —— 这才是"Ant delta 一个字节没丢"的证据。

### 解冲突的三条硬规矩（写死在代码里，不是写在 prompt 里）

1. **没有 skip 这个动作**。解不动只能 `stop`（标记待人工）。`git rebase --skip`
   正是 patch 静默消失的那条路径。要让 patch 退役只能走 `drop` 并写明依据。
2. **`continue` 前必查冲突标记**。文件里还留着 `<<<<<<<` 就直接拒绝。
3. **空 commit 必须显式确认**。解完和 HEAD 没差别 = 这个 Ant patch 正在消失，
   工具会拦下来逼你在 `drop`（上游已吸收）和 `stop`（落点挪了要重贴）之间选。

另外，没报备的 untracked 文件会被拒绝（怕把临时文件打进 commit），要带上用 `--add <path>`。

每条解法都记 `--basis`（trivial / playbook / new / reanchor）和 `--confidence`，
报告按风险从高到低排 —— 人的注意力先给最可能出错的那几个，而不是按 git 碰上的顺序。

**`playbook` 这一档必须复核，不能照抄。** playbook 会过期：实测撞见过 omni PR32 的记录
写着「HEAD 和 incoming 都要保留」，但上游那时已经有了 `_resolve_audio_format`（Ant 版的超集），
照抄就会塞进一段重复实现。

## 跑一轮

```bash
vllm-rebase-agent/run.sh                     # 完整一轮（launchd 调的就是这条）
vllm-rebase-agent/run.sh --repo vllm-ant     # 只跑一个仓库
python3 vllm-rebase-agent/agent.py status    # 看配置 + 上一轮结果
python3 vllm-rebase-agent/agent.py run --no-fetch   # radar，不抓远端，调试用
python3 vllm-rebase-agent/agent.py render --stdout  # 用上一轮数据重新渲染报告
```

手工解冲突（平时不用，排障时有用）：

```bash
A=vllm-rebase-agent/agent.py
python3 $A resolve start --repo vllm-ant --task tracker   # 先 tracker，它的候选分支是后两个的基线
python3 $A resolve status
python3 $A resolve continue --basis playbook --confidence high --note "依据…"
python3 $A resolve drop --reason "逐行核实已在上游…"       # 让 patch 退役
python3 $A resolve stop --reason "…"                       # 交人工
python3 $A resolve finish                                  # 体检 + 落候选分支
```

候选分支只在本地：`git -C ~/.cache/vllm-rebase-agent/<仓库名> log rebase-agent/daily-candidate`。

产物：`reports/<date>.md`（报告）、`state/last-run.json`（结构化结果）、
`logs/vllm-rebase-*.log`（运行日志）。

## 装 / 改 / 停定时

```bash
scripts/install-schedule.sh vllm-rebase-agent --at 07:40
scripts/install-schedule.sh vllm-rebase-agent --status
scripts/install-schedule.sh vllm-rebase-agent --uninstall
launchctl kickstart -p gui/$(id -u)/local.vllm-rebase-agent    # 立即试跑
```

## 架构

```
run.sh                       环境 + 降级兜底（不碰数据）
 ├─ agent.py run             机械部分：抓远端 → 隔离 worktree → 演练 → 记录 → 渲染事实报告
 │    pipeline/gitutil.py      git 薄封装 + worktree 管理 + 冲突分类
 │    pipeline/tasks.py        三个任务的执行 + diff-of-diffs 对齐
 │    pipeline/verify.py       产物体检（也是推送的唯一闸门）
 │    pipeline/report.py       渲染 Markdown
 ├─ claude + .claude/skills/vllm-rebase.md    判断部分：每个冲突该怎么解
 └─ agent.py notify          macOS 通知
```

三个任务（`config/tasks.json`，按顺序跑，后面的用前面的产物）：

| 任务 | 做什么 | 对应的人工动作 |
|---|---|---|
| `tracker` | 社区 main **merge** 进 `public_tracker` | 平时同步上游 |
| `daily` | Ant delta **rebase** 到最新社区 main | 提前暴露上游重构的影响 |
| `release` | Ant delta **rebase** 到最新 release tag | `ant/releases/vX.Y.Z` 的预演 |

`tracker` 失败时，`daily`/`release` 退回用裸 `ant/public_tracker` 当 source，
并在报告里标出来 —— 这种情况下 delta 对齐检查会**跳过**（见下面第 3 条）。

## release 独有提交审计

每轮 radar 顺带跑 `pipeline/release_audit.py`：拿最近一个**非空**的 `ant/releases/*`，
把它的 Ant 提交逐个和 delta 来源对照，报出「只在 release 上、上游也没有」的提交。
空壳分支（只建了分支、没做 rebase 的）会单独列出、不参与比对。

为什么要有它：delta 对齐只能证明「结果 ≡ 来源」，来源本身漏了东西时照样全绿。
两个仓库各撞上过一次——vllm-ant 的 DeepGEMM 修复只在 `public_tracker_daily`，
omni 的三个引擎修复只在 `ant/releases/v0.26.0`——都是人工逐个比对才发现的。

## 七个反直觉的坑（改代码前先看）

1. **一次跑到底，不停在第一个冲突**。遇到冲突记下来就 `git rebase --skip` 继续，
   这样一轮能看到全部冲突面。代价是被 skip 的 patch 不在结果树里，后面的冲突可能
   是连带的 —— 报告里标了「连带冲突」，别当独立问题去修。

2. **rebase 会交换 ours/theirs**。回放时 `git status` 的第一个字母是**新 base**，
   第二个才是那个 Ant patch，和 merge 时正好相反。同一个 `DU`，rebase 下是
   「上游删了文件、patch 还在改它」，merge 下是「public_tracker 删了、main 改了」。
   `gitutil.conflict_entries(cwd, mode)` 的 `mode` 必须如实传。

3. **source 落后 main 时，diff-of-diffs 无意义**。`git diff main..public_tracker`
   在 public_tracker 没合 main 时，除了 Ant delta 还含「把 main 几百个提交倒过来」的
   反向改动。实测 omni 上报到 **53 万行差异**。所以对齐检查前先 `merge-base
   --is-ancestor`，不满足就跳过并说明，**不是判定为"对不上"**。

4. **语法检查只查解冲突动过的文件**。本脚本跑在 `/usr/bin/python3`（3.9），而 vLLM
   要求 3.10+。拿 3.9 去编译上游正常代码会大片误报，实测 2240 个文件报了 2 个假阳性。

5. **只有社区远端能抓 tag**。对内网 `ant` 远端跑 `--tags --prune-tags` 会把本地
   `v0.2x` 系列 tag 全当成"远端已删"清掉，下一步选最新 release tag 就会选错。

6. **选最新 tag 不能用 `git tag --sort=-v:refname`**。它把 `v0.30.0rc2` 排在
   `v0.30.0` 前面（字典序 `rc2 > ''`），于是"最新正式版"会选到 rc。
   用 `gitutil.latest_release_tag()`，它按语义版本排，正式版压过同版本的 rc。

7. **候选分支是持久 ref，跨天还在**。`daily` 拿 tracker 的候选当重放基线时，
   必须确认那是**今天**解出来的（`resolve._fresh_session`）。用昨天的候选当基线，
   会产出一份看起来全绿、其实基线过期的报告 —— 比直接报错危险得多。

## 安全边界

- **绝不碰用户的主 checkout**。所有动作都在 `~/.cache/vllm-rebase-agent/<仓库名>/`
  的专用 worktree、detached HEAD 上做。每轮开始和结束都 `abort_any()` 回干净状态。
- **当前是只读演练，不推送**（`config/tasks.json` 的 `push_enabled: false`）。
  要开推送，把它改成 `true`；三道闸依次是：全局开关 → 任务的 `push.enabled` →
  结果必须 `clean` **且**体检全过。force 推送一律用带期望值的
  `--force-with-lease=ref:sha`，裸 `--force` 从来不用。
- Claude **只能**在 `~/.cache/vllm-rebase-agent/` 的 worktree 里解冲突，不许碰主 checkout、
  不许 push、不许手跑 `git rebase --continue/--skip/--abort`（绕过 `agent.py resolve`
  就意味着解法的依据不会被记录，报告里成了没人能复核的黑历史）。
  见 `.claude/skills/vllm-rebase.md` 的「绝对不要做的事」。
- claude 被看门狗 kill 时，`run.sh` 会 `resolve abort` 清掉半成品树，
  否则第二天 `resolve start` 一上来就失败。

## 降级策略

| 级别 | 情况 | 结果 |
|---|---|---|
| L1 | radar + 解冲突 + 分析都跑完 | 完整报告 + 候选分支 |
| L2 | radar 跑完，代理不通或 Claude 中途挂了 | 事实报告仍在；半成品 worktree 已清理 |
| L3 | `agent.py run` 自己失败 | 告警通知 + 日志 |

全绿的那天不劳烦 Claude，直接发通知。
