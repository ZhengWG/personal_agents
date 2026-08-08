# personal_agents

个人自动化 Agent 集合。用 **Claude CLI + launchd** 把重复的日报工作交给 Agent，定时跑、自动发。

## 🧩 Agents

| Agent | 触发 | 功能 | 详情 |
|-------|------|------|------|
| [daily-ai-infra](./ai-infra-agent/) | 每天 09:00 | 核心盘（23 个推理仓 PR/Release + arXiv + 博客 + HN/Reddit）+ 拓源（Trending / awesome 增量 / 新术语），SMTP 发邮件 | [部署文档](./ai-infra-agent/README.md) |

每个 agent 的部署、配置、排障请看自己的 README。本文件只讲**整个仓库共享的底座**。

## 🏗 共享架构

所有 agent 共用同一个运行模型：

```
launchd  (scripts/install-schedule.sh <agent> 安装)
  └─ <agent>/run.sh                      # agent 的唯一入口（daily / --since range）
       └─ source scripts/_env.sh         # 共享：PATH / 代理 / proxy_ok / run_claude
            └─ claude --print -p "按 .claude/skills/<agent>.md 执行..."
                   └─ .claude/skills/<agent>.md    # 步骤 + 分类规则 + 输出格式（流程真值）
                          ├─ <agent>/agent.py <verb>   # 该 agent 的唯一 CLI（抓取/去重/拓源…）
                          ├─ WebSearch                 # 只留需要判断力的部分（novelty 搜索）
                          └─ scripts/send_mail.py      # 共享 SMTP 发信
```

**分层原则**：`scripts/` 只放**跨 agent 共享**的东西（环境、发信、定时安装器）；
每个 agent 的抓取/处理逻辑全部收在自己目录里，**一个 `run.sh` + 一个 `agent.py`**。
加第二个 agent 不会让 `scripts/` 继续膨胀。

**shell 不碰数据**：`run.sh` 只负责搭环境、调 claude、失败兜底；流程真值只住在 skill 里一份；
数据处理全在 `agent.py` 的子命令里。三者职责不重叠。

**能脚本化的就不要让模型手爬**：HTML 解析、去重、统计一律进 `agent.py`；
只有真正需要判断力的（挑选、总结、novelty 搜索）才留给 Claude。

## 📂 顶层结构

```
personal_agents/
├── README.md                 # 本文件（索引 + 共享底座）
├── CLAUDE.md                 # 项目级 Claude 指令
├── .gitignore                # 屏蔽 logs/ reports/ *.env
│
├── .claude/skills/           # 所有 agent 的任务定义
├── logs/                     # 所有 agent 的运行日志
│
├── scripts/                  # 共享底座，只有 3 个文件
│   ├── _env.sh               #   PATH / 代理 / proxy_ok / run_claude
│   ├── send_mail.py          #   通用 SMTP 发信
│   └── install-schedule.sh   #   通用 launchd 安装器
│
└── ai-infra-agent/           # 一个 agent = 一个自包含目录
    ├── run.sh                #   唯一入口（launchd 调它；--since 走回顾模式）
    ├── agent.py              #   唯一 CLI：fetch/dedup/discover/fallback/stats
    ├── pipeline/
    │   ├── http.py           #     带重试的取数层（全仓唯一 urlopen 出口）
    │   ├── paths.py          #     路径集中解析，不依赖 cwd
    │   └── fetch/discover/dedup/fallback/stats.py
    ├── config/               #   repos.json（机器可读）+ sources.md（人类可读记忆）
    ├── state/                #   seen.json / pending.json / discover.json
    ├── reports/              #   YYYY-MM-DD.md
    └── README.md
```

## 🔧 共享工具

### `scripts/send_mail.py` — 通用 SMTP 发信

纯 Python 标准库，**任何 agent 都可以直接调用**：

```bash
python3 scripts/send_mail.py path/to/report.md
```

凭证统一读 `~/.config/ai-infra-agent/mail.env`（perm 600）。支持任意 SMTP 提供商——465 走 SSL，其他端口走 STARTTLS，**换邮箱只改环境文件，不改代码**。配置细节见 [ai-infra-agent/README.md](./ai-infra-agent/README.md#3-准备发信凭证二选一)。

### `scripts/_env.sh` — 共享运行环境

每个 agent 的 `run.sh` 第一件事就是 source 它。**改 PATH / 代理 / 证书只改这一处**
（以前是三份复制粘贴的 boilerplate，已经漂移过）：

```bash
#!/bin/zsh
set -uo pipefail
source "${0:A:h}/../scripts/_env.sh"   # 同时设好 $REPO
cd "$REPO" || exit 1

if ! proxy_ok; then ... fi                    # 代理预检
run_claude 1200 "按 .claude/skills/<agent>.md 执行..."   # 带看门狗调 claude
```

它解决的几个具体坑（都实测确认过）：

| 坑 | `_env.sh` 的处理 |
|---|---|
| launchd 的 PATH 只有 `/bin:/usr/bin:/usr/ucb:/usr/local/bin` | 显式加 `~/.local/bin`（claude）和 node |
| node 可能是 nvm 也可能是 Homebrew | 按顺序探测，不假设 |
| 交互式 shell 里没有代理变量，直连 API 会 403 | 显式 export（这里是唯一来源） |
| `timeout` 是 Homebrew coreutils，干净 PATH 里没有 | `run_claude` 自带 `sleep + kill` 看门狗 |
| `source ~/.zshrc` 在非交互 shell 会中途中断 | 完全不 source，自包含 |

### 网络不稳怎么办

抓取层的重试住在**各 agent 自己的** `pipeline/http.py`（不是共享的，因为不同 agent
的源特性差别很大）。ai-infra-agent 的策略，可以直接抄：

| 情况 | 行为 |
|---|---|
| 连接重置 / 超时 / DNS 抽风 / 502·503·504 | 重试 3 次，指数退避 + 抖动 |
| 429 或 GitHub 限流（403 带 `X-RateLimit-Reset`） | **按服务端指定的时间等**，不自己拍脑袋 |
| 404 / URL 写错 / 401 | 立即放弃，退避只会白等 |

关键是**别让一次抖动吃掉整个源**：以前单次 `urlopen` 失败就 `except → warn → return []`，
一轮 40 个串行请求，网络差的时候会静默少掉几块内容，日志里只有一行 warning。
跑完打一行 `请求 N 次，重试 M 次，放弃 K 次`，让"网络稳不稳"变成数字而不是猜测。

## 🚀 新增一个 Agent（工程范式）

1. 建目录 `<name>-agent/`，写 `run.sh`（**必须 source `../scripts/_env.sh`**）+ `agent.py`
2. 写 skill：`.claude/skills/<name>.md`，定义信息源、步骤、输出格式
3. 要发邮件？复用 `scripts/send_mail.py`（不要各自实现）
4. 装定时：`scripts/install-schedule.sh <name>-agent --at HH:MM`（launchd，**不要用 crontab**）
5. 写 agent 自己的 README（参考 [ai-infra-agent/README.md](./ai-infra-agent/README.md)）
6. 登记顶层：更新本文件的 Agents 表 + [CLAUDE.md](./CLAUDE.md) 的 skills 列表

## 🔍 常用操作

```bash
scripts/install-schedule.sh ai-infra-agent --status     # 看调度状态 + 最近日志
ai-infra-agent/run.sh                                   # 手工触发（走完整定时路径）
ai-infra-agent/run.sh --since 6mo                       # 主题趋势回顾报告
python3 ai-infra-agent/agent.py --help                  # 看该 agent 的所有子命令
python3 ai-infra-agent/agent.py discover --no-record --pretty   # 单独看今天拓源探到什么
python3 ai-infra-agent/agent.py stats <报告> --budget 20        # 量阅读时间
ls -t logs/daily-ai-infra-*.log | head -1 | xargs less  # 看最近日志
scripts/install-schedule.sh ai-infra-agent --uninstall  # 暂停调度
```

## 🛡 安全

- `.gitignore` 已屏蔽 `logs/` `ai-infra-agent/reports/` `**/*.env`——**不要 commit 凭证**
- SMTP 凭证放 `~/.config/ai-infra-agent/mail.env`（perm 600），**不在 repo 里**
- 拓源注册表 `ai-infra-agent/config/sources.md` **只存源与术语，不存任何凭据**
- 用 launchd 而非 cron，顺带绕开了「给 `/usr/sbin/cron` 配 Full Disk Access」这个要求

## 📎 依赖

- **macOS** —— 定时用 launchd；Linux 需改用 systemd timer（`install-schedule.sh` 只支持 launchd）
- **Claude Code CLI** —— 已登录。原生二进制，**不依赖 node**
- **Python 3.9+** —— 全部只用标准库，**不需要 pip 装任何包**（系统自带的 `/usr/bin/python3` 就够）
- **Node** —— 本仓当前没有 agent 需要它；`_env.sh` 仍会按 nvm → Homebrew 探测，留给以后用 npm 工具的 agent
- 具体 agent 的额外依赖（如 SMTP 凭证）见各 agent 的 README
