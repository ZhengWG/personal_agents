# Personal Agents

个人自动化 agent 集合。

## Skills

- `/daily-ai-infra` — 每天 09:00 抓取 AI infra 推理动态，生成日报并邮件发送。凭证读 `~/.config/ai-infra-agent/mail.env`。
  - **两条腿**：核心盘（`agent.py fetch`，23 个仓 + arXiv + 博客 + HN/Reddit）+ 拓源（`agent.py discover`，
    GitHub Trending / awesome 增量 / 新术语识别 + Claude 的 novelty 搜索）。
  - **两份源配置**：`config/repos.json` 机器可读（喂 `agent.py fetch`，自动晋升）、
    `config/sources.md` 人类可读（候选观察 + 已知术语基线，喂 discover）。改仓库时**两个都要动**。
  - 定时用 launchd 不用 crontab：`scripts/install-schedule.sh ai-infra-agent`。
  - **入口只有一个** `ai-infra-agent/run.sh`；**CLI 只有一个** `ai-infra-agent/agent.py <verb>`。
    `scripts/` 里只放跨 agent 共享的三样：`_env.sh` / `send_mail.py` / `install-schedule.sh`。

- `/vllm-rebase` — 每天 07:40 在隔离 worktree 里演练 `vllm-ant` / `vllm-omni-ant` 的 Ant delta
  rebase，提前暴露冲突 / 掉 patch / delta 漂移。
  - **会推送，但分两档**（2026-10-15 起 `push_enabled: true`）：`daily` / `release` 解完冲突
    且验收通过就自动 `--force-with-lease` 推（演练分支，每天覆盖，解错了明天重来）；
    `tracker` 的解冲突产物**永不自动推**（`after_resolve: false`）—— 它的解法会沉进
    `public_tracker` 历史、成为往后每轮 rebase 的 delta 来源，错一次天天带着，只能人工
    cherry-pick。唯一例外是机械 merge 本来就干净那几天，走 `maybe_push` 推 `public_tracker`。
  - **推送五道闸**：全局开关 → 任务 `after_resolve` → 会话是本轮的（按 `started` 比时间戳，
    否则会把上一轮的候选树推上去）→ 无交人工、无 🔴 低自信 → 六项验收全过。
    失败模式是"不推"而不是"推错"；真的 git push 失败会在通知标题上出现 `· 推送失败`。
  - **两种模式**：`agent.py run` 是 radar（遇冲突 skip 继续，一轮看全冲突面）；
    `agent.py resolve` 是逐个解（停下等 Claude 解完再走，产出完整候选分支）。
    每天两遍都跑 —— delta 对齐只有在 rebase 真正跑完时才有意义。
  - **机械与判断分离**：`agent.py` 只做 git 动作和记录，怎么解冲突交给 Claude 读
    各仓库自带的 `ant-release-rebase` skill（每轮从 `ant/public_tracker` 抠到
    `state/playbook/<仓库名>/`，两个仓库的 playbook **不通用，且会过期，必须复核**）。
  - **解冲突没有 skip 这个动作**：解不动只能 `stop` 交人工，让 patch 退役只能 `drop`
    并写明依据。冲突标记残留、空 commit、没报备的 untracked 都会被工具拒绝。
  - **绝不碰主 checkout**：所有动作在 `~/.cache/vllm-rebase-agent/<仓库名>/` 的
    detached worktree 里；分析步骤的 Claude 也不许改仓库，只能改报告的分析段。
  - **claude 阶段耗时涨了别急着精简 playbook**：2026-10-13 到 10-16 从约 1600 秒涨到
    3196 秒，而解法数一直是 1/5/2/1/6 没变 —— 涨的不是解冲突，是会话之外的复核。
    实测分布：会话内解冲突只占 39%，其余 61% 是读 playbook + 逐条去上游查 sha /
    比行号 / 跑 `--is-ancestor`（note 里留痕可查），这是 playbook 自己要求的"必须复核"。
    查过一轮 30 条解法的引用情况：**playbook 几乎每条都在用**，连 v0.23.0 的冲突 1/2/3
    都还在引用，删哪条都会让对应解法从 `basis=playbook` 掉回 `new`，更容易被标低自信。
    `daily` 和 `release` 看着在重复复核，但两者 base 不同（main vs RC tag），同一条结论
    在两边可能不成立（`#8751` 就是 main 有 rc1 没有），砍掉会解错。
    结论：这是尽职的代价不是浪费，该调的是 `WATCHDOG`，不是 playbook。
  - 六个反直觉的坑（rebase 交换 ours/theirs、source 落后 main 时对齐检查无意义、
    py3.9 对 vLLM 的语法误报、内网远端不能抓 tag、tag 排序、一次跑到底）
    都写在 [vllm-rebase-agent/README.md](./vllm-rebase-agent/README.md)，**改代码前先看**。

## 环境说明

- **所有环境设置集中在 `scripts/_env.sh`**，被各 agent 的 `run.sh` source。改 PATH/代理/证书只改这一处。
  它同时提供 `proxy_ok`（代理预检）和 `run_claude <秒> <prompt>`（带看门狗调 claude）。
- **不要 `source ~/.zshrc`** 取环境：交互式 zshrc 在非交互 shell 下会中途中断，
  导致代理没设上、claude 直连 API 触发 403。
- **launchd/cron 的 PATH 只有 `/bin:/usr/bin:/usr/ucb:/usr/local/bin`**，不含 `/opt/homebrew/bin`。
  node 必须显式加进 PATH（`_env.sh` 已按 nvm → Homebrew 顺序探测）。
- Node.js 本机是 **Homebrew** 装的（`/opt/homebrew/bin/node`），不是 nvm。`~/.nvm` 不存在。
- `claude` 是原生 Mach-O 二进制（`~/.local/bin/claude`），**不依赖 node**。
- 别用 `timeout` 命令：那是 Homebrew coreutils 的，干净 PATH 里没有。用 `run_claude`。

### 本机依赖状态（2026-08-08 核实）

| 依赖 | 状态 |
|---|---|
| `~/.config/ai-infra-agent/mail.env` | ✅ 已配置（QQ SMTP，perm 600），发信实测通过 |
| 完整管线端到端 | ✅ 2026-08-08 经 `launchctl kickstart` 走生产路径跑通 |
| LaunchAgent | ✅ 已装 `local.ai-infra-agent`，每天 **09:00（America/New_York）** 触发 |

改时间/卸载：`scripts/install-schedule.sh ai-infra-agent --at HH:MM|--uninstall`。
**注意 launchd 按系统本地时区触发**，机器换时区后要重新确认。

### 跑一轮的时间画像（用于设看门狗）

Step 1 抓取+去重 ~4.5 分钟（`fetch_github_prs` 单独就 47 秒，**全串行，是明确优化点**）·
拓源+回写+骨架 ~4 分钟 · 总结+增量写报告 ~8 分钟。**总计 10–17 分钟**（取决于当天增量多少），
看门狗 1800 秒有余量。

### 三个反直觉的坑（改代码前先看）

1. **dedup 必须两阶段提交**：`agent.py dedup` 只写 `state/pending.json`，
   发信成功后才 `--commit` 进 `seen.json`。在抓取阶段就标记已读 → 中途崩溃 =
   条目被吞掉且第二天不再出现。
2. **降级判断要看产物新鲜度**：`run.sh` 的 `fresh()` 要求 mtime ≥ 本轮启动时间。
   只判断"文件非空"会把上一轮的旧报告当成本轮半成品重发。
3. **`run_claude` 的看门狗用 `&&` 不用 `;`**：写成 `( sleep N; kill )` 时，
   杀掉 sleep 想取消看门狗，反而会让它立刻执行 kill。

### 网络不稳

取数统一走 `ai-infra-agent/pipeline/http.py`（全仓唯一 `urlopen` 出口）：瞬时错误重试 3 次
（指数退避 + 抖动），429/限流按服务端 `Retry-After` 等，404 立即放弃。
跑完打 `请求 N 次，重试 M 次，放弃 K 次`。**别在别处直接 `urlopen`**。
