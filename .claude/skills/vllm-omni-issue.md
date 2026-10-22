# vllm-omni-issue — 社区 issue 分诊 + 手动修复

`vllm-omni-issue-agent/run.sh` 有两种模式，prompt 会告诉你是哪一种：

- **每日分诊**（launchd 每天 15:00）：`agent.py scan` 已经把近 21 天新开、没 assignee、
  没 closing 关联 PR 的 bug 搜出来，并读过每个的 timeline，标好了有没有人在做。
  **你负责判断**：哪些值得修、在 H20 上能不能复现、要几张卡、什么模型。只读。
- **修复**（用户手动 `run.sh --fix <号>`）：`agent.py fix start` 已经开好本地分支和隔离
  worktree。**你负责**：起 pod 占卡 → 装环境拉模型 → 复现 → 修 → 回归测试 → 提交到本地分支
  → 写修复报告。

```bash
A=~/Projects/personal_tools/personal_agents/vllm-omni-issue-agent/agent.py
REPO=~/Projects/workspaces/vllm-omni-ant      # 主 checkout，只能读 origin/main
```

## 绝对不要做的事

- **不往 GitHub 发任何东西**：不 push、不评论、不认领、不开 PR、不打 label。上游的
  AI Usage Policy 要求 PR 作者本人回答 contributor intent gate、披露 AI 使用，agent 代答就是违规；
  非 committer 还有 5 个未合 PR 的上限。提不提、什么时候提，是人的决定。
- **不动主 checkout**（`$REPO` 的工作区和它当前的分支）。分诊阶段读代码只用
  `git -C $REPO show origin/main:<路径>` / `git -C $REPO grep -n <词> origin/main -- vllm_omni/`；
  修复阶段只在 `state/fix.json` 里的 worktree 改。
- **不手动 kubectl apply / delete / exec**。pod 只走 `agent.py pod …`：它只删自己打过注解的对象、
  卡数有上限、占卡和放卡有顺序。节点上别人的 pod 和卡一概不碰。
- **不自己设 `CUDA_VISIBLE_DEVICES`**。挑好的卡已经写进 pod 的环境，覆盖它就会用到别人的卡。
- **提交只走 `agent.py fix commit`**：它自动 `-s`（上游要 DCO）、拒绝 AI 署名、拒绝冲突标记和
  没报备的新文件。commit message 里不写任何 AI / 工具署名。

---

## 一、每日分诊

### 1. 读候选

```bash
python3 -c "
import json; c = json.load(open('$(dirname $A)/state/candidates.json'))
for it in c['items']:
    print(it['number'], it['status'], 'NEW' if it['new'] else '', it['hw'], it['labels'], it['title'][:90])
"
```

只判 `unclaimed` 和 `stale-claim`（认领超过 14 天没下文）的；`unchecked`（限流没读到 timeline）
的先 `agent.py issue <号>` 看评论再决定。`claimed` / `maybe-fixed` 不用判。`🆕`（昨天没有的）优先。

### 2. 逐个读全文

```bash
python3 $A issue 9242          # 正文 + 全部评论 + 认领判断（state/issues/9242.md）
```

扫描时已经把每个读过 timeline 的 issue 全文落到 `state/issues/<号>.md`，`issue` 命令直接读它，
不调 API；要看扫描之后的新评论才加 `--refresh`（未认证 API 每小时只有 60 次，扫描用掉一半）。
candidates.json 里的 `excerpt` 是截断的，判断前必须读全文。扫描只查了**评论**里的认领，
没查**正文**：作者在正文里写了 "I'll submit a PR" / 勾了 "willing to submit a PR" 的，算已认领。
外部仓库（下游 fork）的 PR 提到它不算认领，但如果外部已经有修法，值得在分析里提一句。

### 3. 去代码里找落点

在 `origin/main` 上定位疑似出错的地方，给到文件和行号。读不到确切落点的，结论不能给 `fix`。

### 4. 下结论并落盘

```bash
python3 $A triage add 9242 --verdict fix --cards 1 --model Qwen/Qwen3-Omni-30B-A3B-Instruct \
  --effort S --reason "add_lora 把 LoRARequest 包成 list 传给 AR worker，落点 vllm_omni/…:123，单卡可复现"
```

| verdict | 什么时候用 |
|---|---|
| `fix` | 真 bug（不是用法问题 / 需求），在 H20 上能复现，卡数 ≤ 上限，根因能定位到具体代码，修法范围小，能写回归测试 |
| `maybe` | 看着能修但有前提：复现条件不清、要维护者先定设计、只在 CI 环境出现、性能回退要先测基线 |
| `skip` | 我们复现不了的硬件（NPU / XPU / ROCm / Blackwell 专属特性）、卡数超上限、安全报告、其实是提问或需求、已有人在修 |

- **卡数**按复现要的模型和并行度估：H20 单卡 96GB；纯 Python 逻辑、CPU 单测能复现的填 `0`
  （仍然要起 pod，Mac 上没有 vLLM 环境）。上限见 `config/agent.json` 的 `max_cards`，超了就 `skip`。
- **模型**写 issue 里的确切 HF id；能复现就挑最小的那个变体。只在 ModelScope、或者 gated 拿不到的，写进理由。
- `hw` 字段只是关键词命中：标着 `[B200]` 的 CI 失败不少在 Hopper 上也能复现，读完再判。

### 5. 写分析

```bash
python3 $A render       # 先刷新事实部分（含你刚落盘的分诊表），再写分析，反过来会被冲掉
```

改写 `reports/<今天>.md` 里 `<!-- claude-analysis -->` 之后的内容：

```markdown
<!-- claude-analysis -->

### 结论

一句话：今天最值得做的 1–3 个是哪几个，为什么这么排。

### #9242 <标题>

- 现象：……
- 根因猜测：`vllm_omni/xxx.py:123` 的 ……（origin/main @ <sha>）
- 复现：模型 / 卡数 / 一条命令
- 修法：……；风险：……

### 不适合的

- #9191 —— NPU 专属，H20 复现不了
```

只给 `fix` / `maybe` 写小节，`skip` 一行一条。宁可短。

### 6. 收尾

只输出：判了几个 fix / maybe / skip，最推荐哪一个，以及它的 `run.sh --fix` 命令。

---

## 二、修复

输入：`state/fix.json`（issue、branch、worktree、base）、`state/issues/<号>.md`、最近一份分诊报告。

### 0. 先看还该不该做

- `state/issues/<号>.md` 顶部的「认领判断」不是 `unclaimed` / `stale-claim` → 别人在做了，
  直接写一份只有结论的修复报告（「已被认领：……」）就收尾，**不起 pod**。
- 上游的 contributor intent gate（`$WT/.claude/skills/precheck-pr/SKILL.md`）要求人亲自回答
  4 个问题，**你不能代答**。本地分支可以先做，但报告里这 4 问留给人填。

### 1. 读 issue 和仓库自带的 skill

worktree 里有上游维护的 skill，按需读：`.claude/skills/vllm-omni-test/SKILL.md`
（测试分级 L1–L4、marker、命令写法）、`precheck-pr/SKILL.md`（自检清单）、
`docs/contributing/ci/lessons.md`（和这次改动相关的条目）。

### 2. 起 pod、占卡、准备环境

```bash
python3 $A pod up --cards 1                 # 建 pod → 挑空卡 → 立刻占住；输出里有节点和卡号
python3 $A pod prep --model Qwen/Qwen2.5-Omni-3B   # 同步代码 + 对齐 vllm 版本 + pip install -e . + 拉模型
```

- `pod up` 会依次试配置里的节点，凑不出空卡就换下一个。卡号在输出的 `gpus` 里。
- **从 `pod up` 到 run.sh 删 pod，卡一直占着**。拉模型、装环境、你读代码想方案的时候都占着，
  只有 `pod run --gpu` 那条命令跑的时候放给它用，跑完立刻占回来。
- `prep` 很慢（vllm 版本对不上要现装、模型几十 GB），它在后台跑，`--wait 540` 等不完会提示
  `agent.py pod wait <id>`，接着等就行。**这几条 Bash 调用要设 `timeout: 600000`**。
- 环境装不上（pip 冲突、模型拿不到）就如实写进报告收尾，不要硬凑一个"差不多"的环境去下结论。

### 3. 先证明它确实坏了

改代码之前，在没改过的分支上复现：

```bash
python3 $A pod run --gpu -- 'python3 examples/xxx.py --model … 2>&1 | tail -50'
python3 $A pod log <id> --grep 'Traceback|Error'
```

记下预期 vs 实际、base 的 sha、环境（镜像、vllm 版本、卡）、命令、关键日志。
**复现不出来就不修**：上游明确说"看着对的诊断、没跑过的复现脚本"都不算失败证据。
换几种方式仍复现不了，写报告说明卡在哪，收尾。

### 4. 回归测试 → 修 → 验证

1. 先写一个在 base 上**失败**的回归测试（照 vllm-omni-test 的分级，能 L1 就别 L2）。
2. 在 worktree 里改代码。`pod run` 每次都会先把 worktree 当前内容（含没提交的改动）
   同步进 pod，不用先提交。
3. 回归测试通过 → 再跑和改动相关的既有测试（窄一点，别跑全量）。

```bash
python3 $A pod run --gpu -- 'pytest -x -q tests/xxx/test_yyy.py::test_zzz'
python3 $A pod run -- 'pytest -x -q -m "core_model and cpu" tests/xxx/'   # CPU 测试不用 --gpu
```

`pod run` 不带 `--gpu` 时卡还占着，测试只能用 CPU。整条命令用一个引号包起来。
另一条命令还在后台跑时，新的 `pod run` 要加 `--no-sync`，否则同步会改掉它正在用的代码。

### 5. Lint 和提交

```bash
python3 $A pod run -- 'pre-commit run --files vllm_omni/xxx.py tests/xxx/test_yyy.py'
python3 $A fix commit -m "[Bugfix] Fix LoRA request wrapping for AR stages

<改了什么、为什么；一两段>

Fixes #9242" --add tests/xxx/test_yyy.py
```

标题用上游的 PR 分类前缀（`[Bugfix]` 等）。新文件要 `--add` 报备，临时脚本删掉别带上。

### 6. 写修复报告 `reports/fix-<号>.md`

```markdown
# #<号> <标题> — 修复报告

- 结论：✅ 修好了 / ⚠️ 没修完（卡在哪）/ ❓ 复现不了 / ⏭️ 已被认领
- 分支：`<branch>`（worktree `<路径>`，base `<sha>`），提交：`<sha> <标题>`

## 失败证据（修复前）
预期 / 实际 / 版本（base sha、镜像、vllm、卡型和卡数）/ 命令 / 关键日志

## 根因
## 修复
## 验证
每条命令和结果（修复前失败 → 修复后通过），硬件和模型；**没跑的检查单独列出来**

## 提 PR 之前要你做的
- [ ] 回答 intent gate 4 问：想达成什么结果？最关键的变量是什么？这次改动怎么推动它？解决谁的什么需求？
- [ ] 逐行 review 改动，确认自己能解释每一处
- [ ] AI 使用披露：上游 AI Usage Policy 要求在 PR 描述里写明用了什么工具、做了什么；
      这和你的全局规则（commit / PR 不写 AI 署名）冲突，提之前自己定
- [ ] 推送：`git -C <worktree> push origin_zwg <branch>`，再开 PR
```

pod 不用你删，run.sh 收尾时会删（`--keep-pod` 时只放卡）。

### 7. 收尾

只输出：结论一句、分支名、提交 sha、报告路径。
