# daily-ai-infra — AI 推理优化日报 Agent

每天固定时间（默认 09:00）自动抓取 AI infra 推理相关公开源的最新动态，用 Claude CLI 分类整理成日报，邮件发送到指定邮箱。

## 抓取源（公开，无需 token）

| 类别 | 源 | 抓取手段 |
|------|-----|---------|
| GitHub PR | `sgl-project/sglang` | WebFetch 搜索页 |
| GitHub PR | `vllm-project/vllm` | WebFetch |
| GitHub PR | `vllm-project/vllm-omni` | WebFetch |
| GitHub PR | `sgl-project/sglang-omni` | WebFetch |
| 论文 | arXiv cs.LG recent + HuggingFace Papers | WebFetch |
| 博客 | HuggingFace Blog、Interconnects AI、The Neuron | WebFetch |
| 社区 | Reddit r/LocalLLaMA top of day | `curl` JSON |

输出结构见 `reports/2026-04-19.md` 示例。

## 顶层架构

```
┌─────────────┐     cron 0 9 * * *
│   crontab   │─────────────────────────┐
└─────────────┘                          │
                                         ▼
                    ┌──────────────────────────────────┐
                    │  scripts/daily-ai-infra-cron.sh  │  加载 nvm PATH + NO_PROXY
                    └──────────────────────────────────┘
                                         │
                                         ▼
                    ┌──────────────────────────────────┐
                    │  claude --print (Claude CLI)     │
                    │  按 skill 步骤执行                │
                    └──────────────────────────────────┘
                                         │
            ┌────────────────────────────┼────────────────────────────┐
            ▼                            ▼                            ▼
     WebFetch × 7 源             curl Reddit JSON          Claude 分类总结
            │                            │                            │
            └────────────────────────────┴────────────────────────────┘
                                         │
                                         ▼
                           reports/YYYY-MM-DD.md
                                         │
                                         ▼
                    ┌──────────────────────────────────┐
                    │  scripts/send_mail.py            │
                    │  读 ~/.config/ai-infra-agent/    │
                    │    mail.env 发 Gmail SMTP        │
                    └──────────────────────────────────┘
                                         │
                                         ▼
                                    📧 收件人
```

## 环境要求

| 组件 | 最低版本 | 说明 |
|------|---------|------|
| macOS / Linux | — | 用 crontab 调度；Windows 需改用 Task Scheduler |
| Claude Code CLI | 1.0+ | 已登录。`claude --version` 验证 |
| Node.js | ≥ 20 | 通常由 nvm 装；脚本会自动把 nvm 的 node bin 加入 PATH |
| Python | 3.8+ | 用于 SMTP 发信（仅用标准库，无需 pip 装包） |
| Gmail 账号 | — | 开启 2FA，生成 App Password |

## 一键部署（新环境）

### 1. 拉仓库

```bash
git clone <this-repo> ~/Projects/personal_agents
cd ~/Projects/personal_agents
```

### 2. 验证 Claude CLI 可用

```bash
claude --version
claude --print -p "ping" | head -3   # 确认能调通
```

如未安装，参考 [Claude Code 官方安装](https://claude.com/claude-code)。

### 3. 准备 Gmail 凭证

1. 打开 `https://myaccount.google.com/apppasswords`（需先开启 2FA）
2. 新建一个 app password（名字写 `ai-infra-agent`），复制 16 位密码
3. 创建凭证文件：

```bash
mkdir -p ~/.config/ai-infra-agent
cat > ~/.config/ai-infra-agent/mail.env <<'ENV'
SMTP_HOST=smtp.gmail.com
SMTP_PORT=465
SMTP_USER=your_sender@gmail.com
SMTP_PASS=xxxxxxxxxxxxxxxx
MAIL_TO=your_receiver@gmail.com
MAIL_FROM=AI Infra Daily <your_sender@gmail.com>
ENV
chmod 600 ~/.config/ai-infra-agent/mail.env
```

### 4. 脚本加执行权限

```bash
chmod +x scripts/daily-ai-infra-cron.sh scripts/send_mail.py
```

### 5. 手工试跑一次（最小 smoke test）

**只测邮件**（用已有的 2026-04-19 示例报告）：

```bash
/usr/bin/python3 scripts/send_mail.py ai-infra-agent/reports/2026-04-19.md
# 预期: MAIL SENT → your_receiver@gmail.com (subject: ...)
```

**跑完整管线**（抓取+生成+发信，约 2-5 分钟）：

```bash
./scripts/daily-ai-infra-cron.sh
tail -f logs/daily-ai-infra-*.log   # 另开终端看日志
```

成功的尾行应包含 `MAIL SENT`。

### 6. 装 crontab

```bash
# 追加，不要覆盖已有 crontab
( crontab -l 2>/dev/null; \
  echo '# 每天 09:00 AI infra 推理日报'; \
  echo '0 9 * * * '"$HOME"'/Projects/personal_agents/scripts/daily-ai-infra-cron.sh' \
) | crontab -

crontab -l   # 验证
```

**macOS 注意**：crontab 里用绝对路径；且系统需给 `cron` 进程 Full Disk Access（System Settings → Privacy → Full Disk Access → 添加 `/usr/sbin/cron`），否则 Claude CLI 可能读不到 `~/.claude/`。

### 7. 完成

明天 09:00 自动触发，日志落 `logs/daily-ai-infra-YYYYMMDD-HHMMSS.log`。

## 自定义

### 改触发时间

编辑 crontab 行的 cron 表达式：

```
# 每天 08:30
30 8 * * * ~/Projects/personal_agents/scripts/daily-ai-infra-cron.sh

# 工作日 09:00
0 9 * * 1-5 ~/Projects/personal_agents/scripts/daily-ai-infra-cron.sh
```

### 增删抓取源

编辑 `.claude/skills/daily-ai-infra.md`：

- 加 GitHub 仓：复制 Step 2 里的一行 URL，把 `sgl-project/sglang` 换成目标仓
- 加 RSS/博客：在 Step 4 追加 URL
- 加领域关键词（过滤 arXiv / Reddit）：改 Step 3 / Step 5 的筛选提示词

### 换收件人 / 多收件人

`mail.env`：

```
MAIL_TO=user1@x.com,user2@y.com
```

（`send_mail.py` 已支持逗号分隔）

### 换 SMTP（非 Gmail）

`mail.env`：

```
SMTP_HOST=smtp.qq.com      # 示例
SMTP_PORT=465              # SSL；如用 STARTTLS 改 587
SMTP_USER=xxx@qq.com
SMTP_PASS=<授权码>
```

`send_mail.py` 对 465 走 SSL、其他端口走 STARTTLS，无需改代码。

## 文件清单

```
personal_agents/
├── .claude/
│   └── skills/
│       └── daily-ai-infra.md          # Skill 定义（抓取 + 分类 + 邮件步骤）
├── scripts/
│   ├── daily-ai-infra-cron.sh         # cron 入口（加载 PATH + 调 claude）
│   └── send_mail.py                   # SMTP 发信（markdown→HTML）
├── ai-infra-agent/
│   ├── README.md                      # 本文件
│   └── reports/
│       └── YYYY-MM-DD.md              # 每日生成的日报
└── logs/
    └── daily-ai-infra-YYYYMMDD-HHMMSS.log
```

凭证文件（不进 git）：
```
~/.config/ai-infra-agent/mail.env      # perm 600
```

## 排障

### 邮件没发出

```bash
# 1) 看日志
ls -t logs/daily-ai-infra-*.log | head -1 | xargs tail -80

# 2) 单独测发信
/usr/bin/python3 scripts/send_mail.py ai-infra-agent/reports/2026-04-19.md
```

常见原因：

| 现象 | 排查 |
|------|------|
| `MAIL FAILED: env file not found` | 确认 `~/.config/ai-infra-agent/mail.env` 存在，且执行用户可读 |
| `MAIL FAILED: (535, ...)` 认证失败 | App Password 写错；Gmail 要求 16 位、无空格；确认开了 2FA |
| `MAIL FAILED: timeout` | 本机网络到 `smtp.gmail.com:465` 不通；办公网可能走代理 |
| 日志里 `command not found: claude` | cron 没继承 PATH；检查 `daily-ai-infra-cron.sh` 里的 nvm PATH 导入；macOS 需要给 cron Full Disk Access |

### 报告没生成

```bash
# 手跑一次看详细输出
./scripts/daily-ai-infra-cron.sh
cat logs/daily-ai-infra-*.log | tail -200
```

- `claude --print` 卡住 → 检查 `claude auth` 是否过期
- 抓取某个源失败但整体应该继续 → skill 已容错，会跳过

### crontab 没触发

```bash
# macOS 看 cron 执行日志
log show --predicate 'process == "cron"' --last 24h | tail -30

# Linux
grep CRON /var/log/syslog | tail -20
```

## 卸载

```bash
# 取消定时
crontab -l | grep -v daily-ai-infra-cron.sh | crontab -

# 删凭证
rm -rf ~/.config/ai-infra-agent

# 删代码（可选）
rm -rf ai-infra-agent scripts/daily-ai-infra-cron.sh scripts/send_mail.py \
       .claude/skills/daily-ai-infra.md
```

## 安全注意

- `mail.env` 权限必须 600，且 **不要 commit 进 git**（项目根 `.gitignore` 应包含 `mail.env`）
- App Password 泄露后立即去 Google 账号页面撤销
- 日志文件可能包含抓取到的 PR 标题等非敏感信息，但不包含邮箱密码；如要长期保留可归档
- 不要把内网 / 公司内部源加进 skill（本 agent 设计上仅消费公开源）
