# personal_agents

个人自动化 Agent 集合。用 **Claude CLI + crontab** 把重复的日报/周报工作交给 Agent，定时跑、自动发。

## 🧩 Agents

| Agent | 触发 | 功能 | 详情 |
|-------|------|------|------|
| [daily-ai-infra](./ai-infra-agent/) | 每天 09:00 | 抓 SGLang / vLLM / vLLM-Omni / SGLang-Omni 的 PR + arXiv + 博客 + Reddit，SMTP 发邮件 | [部署文档](./ai-infra-agent/README.md) |
| weekly-report | 每周四 17:00 | 从语雀知识库读最新一周的工作文档，整理周报并写回语雀 | [skill](.claude/skills/weekly-report.md)（文档待补） |

每个 agent 的部署、配置、排障请看自己的 README。本文件只讲**整个仓库共享的底座**。

## 🏗 共享架构

所有 agent 共用同一个运行模型：

```
crontab
  └─ scripts/<agent>-cron.sh     # 加载 nvm PATH / NO_PROXY
       └─ claude --print -p "按 .claude/skills/<agent>.md 执行..."
              └─ .claude/skills/<agent>.md   # 抓取步骤 + 分类规则 + 输出格式
                     ├─ WebFetch / curl     # 公开源
                     ├─ yuque-cli           # 内网知识库（走 ~/.identitymcp）
                     └─ scripts/send_mail.py # 通用 SMTP 发信
```

新增 agent 只需：**写一个 skill + 一个 cron 脚本 + 追加一行 crontab**。

## 📂 顶层结构

```
personal_agents/
├── README.md                 # 本文件（索引 + 共享底座）
├── CLAUDE.md                 # 项目级 Claude 指令
├── .gitignore                # 屏蔽 logs/ reports/ *.env
│
├── .claude/skills/           # 所有 agent 的任务定义
├── scripts/                  # 所有 agent 的 cron 入口 + 共享工具（send_mail.py）
├── logs/                     # 所有 agent 的运行日志
│
├── ai-infra-agent/           # daily-ai-infra 的数据 + README
└── weekly-yuque-agent/       # weekly-report 的数据
```

## 🔧 共享工具

### `scripts/send_mail.py` — 通用 SMTP 发信

纯 Python 标准库，**任何 agent 都可以直接调用**：

```bash
python3 scripts/send_mail.py path/to/report.md
```

凭证统一读 `~/.config/ai-infra-agent/mail.env`（perm 600）。支持任意 SMTP 提供商——465 走 SSL，其他端口走 STARTTLS，**换邮箱只改环境文件，不改代码**。配置细节见 [ai-infra-agent/README.md](./ai-infra-agent/README.md#3-准备发信凭证二选一)。

### cron 脚本模板

所有 `scripts/*-cron.sh` 遵循同一套 boilerplate：

```bash
#!/bin/bash
set -euo pipefail

# 1. 加载 nvm PATH（cron 不走 .zshrc）
export NVM_DIR="$HOME/.nvm"
_nvm_bin="$(ls -d "$NVM_DIR/versions/node/"*/bin 2>/dev/null | sort -V | tail -1)"
[ -d "$_nvm_bin" ] && export PATH="$_nvm_bin:$PATH"

# 2. 代理豁免（如需访问内网）
export NO_PROXY="localhost,*.alipay.com,*.antfin.com,..."

# 3. 日志重定向
LOG="$HOME/Projects/personal_agents/logs/<agent>-$(date +%Y%m%d-%H%M%S).log"

# 4. 驱动 Claude CLI 执行 skill
cd "$HOME/Projects/personal_agents"
claude --print --dangerously-skip-permissions \
  -p "按 .claude/skills/<agent>.md 执行..." >> "$LOG" 2>&1
```

## 🚀 新增一个 Agent（工程范式）

1. 写 skill：`.claude/skills/<name>.md`，定义信息源、步骤、输出格式
2. 写 cron 脚本：`scripts/<name>-cron.sh`，套用上方模板
3. 发邮件/写语雀？复用 `scripts/send_mail.py` / `yuque-cli`
4. 装 crontab：`crontab -e` 追加 `M H * * * /abs/path/to/scripts/<name>-cron.sh`
5. 写 agent 自己的 README（参考 [ai-infra-agent/README.md](./ai-infra-agent/README.md)）
6. 登记顶层：更新本文件的 Agents 表 + [CLAUDE.md](./CLAUDE.md) 的 skills 列表

## 🔍 常用操作

```bash
crontab -l                                  # 看当前调度
~/Projects/personal_agents/scripts/daily-ai-infra-cron.sh   # 手工触发
ls -t logs/daily-ai-infra-*.log | head -1 | xargs less      # 看最近日志
crontab -e                                  # 编辑/暂停某个 agent
```

## 🛡 安全

- `.gitignore` 已屏蔽 `logs/` `ai-infra-agent/reports/` `**/*.env`——**不要 commit 凭证**
- SMTP 凭证放 `~/.config/ai-infra-agent/mail.env`（perm 600），**不在 repo 里**
- 语雀登录态在 `~/.identitymcp`，**不在 repo 里**
- macOS 需给 `/usr/sbin/cron` 配 Full Disk Access，否则 cron 读不到 `~/.claude/` 登录态

## 📎 依赖

macOS / Linux · Claude Code CLI · Node ≥ 20（nvm 即可）· Python 3.8+（标准库）· 具体 agent 的额外依赖见各 agent README。
