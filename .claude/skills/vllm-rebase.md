# vllm-rebase — 每日 rebase 演练的分析步骤

`vllm-rebase-agent/run.sh` 已经把**机械部分**跑完了：抓远端、开隔离 worktree、
把 Ant delta 演练 merge/rebase 到最新社区 main 和最新 release tag、把每个冲突
和每个掉的 patch 记进 `state/last-run.json`，并渲染成 `reports/<date>.md` 的事实部分。

**你负责两件事**：
1. **解冲突** —— 用 `agent.py resolve` 逐个解，产出一棵完整的候选分支（只在本地，不推送）；
2. **写结论** —— 把判断和待人工的部分写进报告的「分析与建议」一节。

## 绝对不要做的事

- **不要动用户的主 checkout**（`~/Projects/workspaces/vllm-ant` 等）。解冲突只在
  `~/.cache/vllm-rebase-agent/<仓库名>/` 的专用 worktree 里做，那是 agent 的地盘。
- **不要 push 任何分支**，也不要改仓库里的任何 ref。候选分支由 `resolve finish` 落在本地，
  推不推由人决定。
- **不要手动跑 `git rebase --continue` / `--skip` / `--abort`**。全部走 `agent.py resolve`，
  否则解法的依据不会被记录，报告里就成了一段没人能复核的黑历史。
- **不要动报告里 `<!-- claude-analysis -->` 之前的内容**。那是机械产出的事实，
  和 `state/last-run.json` 一一对应，改了就对不上了。

## 步骤

### 1. 读输入

```bash
AGENT=~/Projects/personal_tools/personal_agents/vllm-rebase-agent
cat $AGENT/state/last-run.json          # 结构化结果（权威）
ls $AGENT/state/playbook/               # 各仓库抠出来的 ant-release-rebase skill
```

`state/playbook/<仓库名>/` 里是**那个仓库自己**的 playbook（从 `ant/public_tracker`
抠出来的当前版本）。两个仓库的 playbook 不一样，**不要混用**：

| 仓库 | playbook 特点 |
|---|---|
| `vllm-ant` | 单个 SKILL.md。重点是 `--empty=stop` 防静默掉 patch、`_check_model` override 的落点会随版本挪 |
| `vllm-omni-ant` | SKILL.md + 两份 conflict-playbook + verification.md。有一张按文件索引的冲突对照表（`api_server.py` model auto、`serving_chat.py` 的 final_res / modalities / PR32 audio 三类） |

### 2. 逐条判断

报告里每个任务可能出现四类问题，处理思路各不相同：

**⚠️ 冲突（conflicts）** — 对照该仓库 playbook 的冲突表，给出：
1. 这是 playbook 里**已知的**哪一类，还是**新出现的**；
2. 保 HEAD 还是保 incoming 还是两边都要，具体到方法名；
3. 如果是上游重构（方法挪进基类、模块改名），说明 Ant 的改动该落到新位置的哪里。

注意报告里标了**「连带冲突」**的条目：agent 是一次跑到底的，遇到冲突记下来就
`git rebase --skip` 继续，所以后面的冲突可能只是前面 skip 掉 patch 的副作用。
这类要明说「先解决第 N 个之后再看这个还在不在」，不要当成独立问题让人白修。

**🔴 掉 patch（empty_dropped / missing_patches）** — 这是最要紧的一类，
`--empty=stop` 拦下来的每一个都要回答：

- 上游是不是已经**自己做了**这件事？→ 可以不要，但要在报告里写清依据（指出上游的 commit/PR）。
- 还是这个 patch 的**落点挪了**（方法搬进基类、文件改名）？→ 必须重新贴，
  并指出**新落点**：去 `ant/public_tracker` 的当前树里找这个改动现在住在哪个类/文件，
  **不要照抄旧记录里的路径**（SKILL.md 里 v0.25.0 的事故就是落点从 `OpenAIServing`
  挪到了 `GenerateBaseServing`）。

**🟠 delta 漂移（drifted）** — diff-of-diffs 对不上。逐行看报告里的样本：

- 只是上游挪了代码导致的上下文行错位 → 说明「可解释，非问题」。
- 有 Ant 的**业务逻辑**只在一侧出现 → 这就是丢了 patch 或多了东西，按掉 patch 处理。

**🔴 release 独有提交（`last-run.json` 里各仓库的 `release_audit.release_only`）** —— 修复只提交在
最近一个 ant release 分支上、没回灌 delta 来源（`public_tracker`）。delta 对齐查不出这类问题：
它只能证明"结果 ≡ 来源"，来源本身就少东西时它照样全绿。实际撞上过两次（vllm-ant 的 DeepGEMM、
omni 的三个引擎修复）。每一条都要在报告里写明：要不要回灌、回灌到 `public_tracker` 时预计有没有冲突。
**不要自己去回灌**——这会改变 delta 来源，属于人的决定。

**💥 执行失败（error）** — 大多是 fetch 失败、worktree 坏了、或 rebase 没收敛。
写清是环境问题还是仓库状态问题，给出一条能直接跑的修复命令。

### 3. 解冲突（对每个有冲突的 rebase/merge 任务）

用 `agent.py resolve` 的一步一停接口。**顺序很重要**：先 `tracker`，再 `daily`/`release` ——
tracker 解完会落一个候选分支，后两者会自动拿它当重放基线；tracker 没解好，
后两者只能退回那棵落后几百个提交的裸 `public_tracker`，delta 对齐这项就整个失效。

```bash
A=~/Projects/personal_tools/personal_agents/vllm-rebase-agent/agent.py

python3 $A resolve start --repo vllm-ant --task tracker   # 停在第一个冲突，输出 JSON
python3 $A resolve status                                  # 随时问"我现在停在哪"
# ……在 worktree 里改文件解冲突……
python3 $A resolve continue --basis playbook --confidence high --note "依据…"
# ……重复，直到 state=done……
python3 $A resolve finish                                  # 体检 + 落候选分支
```

**四个动作，选哪个**：

| 情况 | 动作 |
|---|---|
| 解好了 | `continue --basis … --confidence … --note "…"` |
| 这个 patch 上游确实已经做了 | `drop --reason "<逐行核实的依据>"` |
| 解不动 / 拿不准 / 要大改 | `stop --reason "…"`，本任务到此为止，交给人 |
| 想推倒重来 | `abort` |

**没有 skip 这个动作**，这是故意的。`git rebase --skip` 正是 patch 静默消失的那条路径
（SKILL.md 里 v0.25.0 的事故）。要让一个 patch 退役，只能走 `drop` 并写明依据，
依据会进报告让人复核。

`--basis` 如实填，它决定报告里的排序（人先看风险最高的）：

- `trivial` —— 空白/格式漂移，没有语义差别
- `playbook` —— 仓库 playbook 里有明确结论，**且你复核过它对当前上游仍然成立**
- `new` —— playbook 没覆盖，你自己判断的
- `reanchor` —— 落点被上游删除/挪走，把 Ant 逻辑重贴到新位置

`--confidence low` 不丢人，写上它比赌对更有价值 —— 报告会把低自信的排到前面。

**三件工具会替你拦住的事**（不用背，撞上了会有明确报错）：

1. 文件里还留着 `<<<<<<<` 就 `continue` → 拒绝；
2. 解完发现 commit 会变空（= 这个 Ant patch 就此消失）→ 拒绝，逼你在 `drop` 和 `stop` 里选；
3. 工作区有没报备的新文件 → 拒绝，怕把临时文件打进 commit（确实要带就 `--add <path>`）。

**解冲突时的两条实质要求**：

- **`playbook` 这一档必须复核，不能照抄。** playbook 会过期。实测撞见过：omni PR32 的记录写着
  「HEAD 和 incoming 都要保留」，但上游那时已经有了 `_resolve_audio_format`（是 Ant 版的超集），
  照抄就会塞进一段重复实现。下结论前去 `origin/main` 的树里 grep 一眼当前形态。
- **落点被删（`DU`）不是"选一边"，是搬家。** 正确做法是 `git rm` 掉死文件，
  把 Ant 逻辑贴到上游的新位置，落点**按 `public_tracker` 当前的树去定**，
  不要照抄旧记录里的路径。工具会把你对其它文件的修改一并 stage。

### 4. 写回报告

先 `python3 $A render` 把解冲突的结果刷进报告的事实部分，**再**写分析段 ——
反过来会把你写的分析冲掉。

改写 `reports/<date>.md` 里 `<!-- claude-analysis -->` 之后的全部内容。结构：

```markdown
<!-- claude-analysis -->

### 结论

一句话：今天要不要人介入，介入的话先做哪一件。

### <仓库名> / <任务名>

**冲突 1：`<sha>` <subject>** — 已知模式 / 新模式
- 判断：……
- 建议：…（具体到文件、类、方法）

**掉 patch：`<sha>` <subject>**
- 判断：上游已吸收 / 落点挪了
- 建议：…

### 需要人做的事

- [ ] 一条条列，能直接照做的粒度
```

**没有问题的任务不用写**，报告的总览表已经说明了。宁可短，不要把事实部分抄一遍。

### 5. 收尾

只输出：解了几个、退役几个、留了几个给人工、最要紧的那一条是什么。报告路径打一行。
