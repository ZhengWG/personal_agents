# daily-ai-infra — AI 推理优化日报 Agent

每天固定时间（默认 09:00）自动抓取 AI infra 推理相关公开源的最新动态，用 Claude CLI 分类整理成日报，邮件发送到指定邮箱。

## 抓取源（全部公开，无需 token）

**核心盘**（`agent.py fetch`）：`config/repos.json` 里 23 个推理仓的 PR + Release（sglang / vllm /
vllm-omni / sglang-omni / TensorRT-LLM / flashinfer / dynamo / Mooncake / lmdeploy / tilelang /
TileRT / tokenspeed / DeepSeek 全家桶 / llm-d / TGI / transformers / llama.cpp）· arXiv
（cs.LG/DC/AR/PF/CL/OS，推理关键词预筛）· HuggingFace Daily Papers · HF 模型发布 ·
Hacker News（Algolia）· Reddit r/LocalLLaMA · 11 个博客 RSS。

**拓源盘**（`agent.py discover`）：GitHub Trending 日/周榜 · topic 搜索的近期高星仓 ·
策展 awesome 清单的增量条目 · 新术语识别。外加 Claude 的 novelty 搜索。

高频被提及的新仓会**自动晋升**进 `repos.json` 的 `tracked`，不用改代码。

## 顶层架构

```
launchd  (每天 09:00)
  └─ ai-infra-agent/run.sh                 唯一入口
       └─ source ../scripts/_env.sh        PATH / 代理 / proxy_ok / run_claude
            └─ claude --print  按 .claude/skills/daily-ai-infra.md 执行
                   ├─ agent.py fetch    ──┐
                   ├─ agent.py dedup      │ 核心盘 → 归一化 JSON → 跨天去重
                   ├─ agent.py discover   │ 拓源：Trending / awesome 增量 / 新术语
                   ├─ WebSearch           │ novelty 搜索（需要判断力，脚本做不了）
                   ├─ agent.py stats      │ 阅读时间自检（>20 分钟就回去砍）
                   └─ ../scripts/send_mail.py  → 📧
                                          │
       └─ 降级兜底（claude 崩了也不空手）  ─┘
            L2 报告填了一半 → 加横幅补发
            L3 只有抓取结果 → agent.py fallback 发原始条目
            L4 什么都没有   → 才发失败告警
```

## 环境要求

| 组件 | 最低版本 | 说明 |
|------|---------|------|
| macOS | — | 用 launchd 调度（`scripts/install-schedule.sh`）；Linux 需改用 systemd timer |
| Claude Code CLI | 1.0+ | 已登录。`claude --version` 验证 |
| Node.js | 可选 | 本 agent **不需要** node（claude 是原生二进制）；`_env.sh` 会按 nvm→Homebrew 探测备用 |
| Python | 3.9+ | 抓取/去重/发信全部只用标准库，**无需 pip 装包** |
| 发信邮箱 | — | QQ 邮箱 / Gmail 任选，都需要生成"授权码/App Password"（不是登录密码） |

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

### 3. 准备发信凭证（二选一）

#### 3a. QQ 邮箱（推荐，国内直连 SMTP 最稳）

1. 登录 `https://mail.qq.com` → **设置** → **账户**
2. 滚到 **POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务** 区域，**开启 IMAP/SMTP 服务**
3. 按提示发短信验证，获得 **16 位授权码**（形如 `abcdefghijklmnop`，只显示一次，立刻保存）
4. 写入凭证文件：

```bash
mkdir -p ~/.config/ai-infra-agent
cat > ~/.config/ai-infra-agent/mail.env <<'ENV'
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USER=你的QQ邮箱@qq.com
SMTP_PASS=16位授权码
MAIL_TO=收件人邮箱
MAIL_FROM=AI Infra Daily <你的QQ邮箱@qq.com>
ENV
chmod 600 ~/.config/ai-infra-agent/mail.env
```

> ⚠ QQ 必须用 **授权码**，不是 QQ 登录密码，否则报 `535 Login fail ... Please use authorized code`。

#### 3b. Gmail（海外网络环境优先）

1. 打开 `https://myaccount.google.com/apppasswords`（需先开启 2FA）
2. 新建 app password（名字写 `ai-infra-agent`），复制 16 位密码
3. 写入凭证文件：

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

> ⚠ 国内网络到 `smtp.gmail.com:465` 常被防火墙/代理拦，走 QQ 更省心。

### 4. 脚本加执行权限

```bash
chmod +x ai-infra-agent/run.sh scripts/send_mail.py
```

### 5. 手工试跑一次（最小 smoke test）

**只测邮件**（先造一份最小报告，不依赖历史文件）：

```bash
printf '📋 发信测试\n\n📌 说明\n● [链接渲染测试](https://github.com/vllm-project/vllm)\n' > /tmp/t.md
/usr/bin/python3 scripts/send_mail.py /tmp/t.md
# 预期: MAIL SENT → your_receiver@gmail.com (subject: 📋 发信测试)
```

**只测抓取**（不调用 claude，约 5 分钟）：

```bash
python3 ai-infra-agent/agent.py fetch --mode daily | python3 ai-infra-agent/agent.py dedup --no-record > /tmp/t.json
python3 ai-infra-agent/agent.py discover --from /tmp/t.json --no-record --pretty | head -40
```

**跑完整管线**（抓取+拓源+生成+发信，约 17 分钟）：

```bash
./ai-infra-agent/run.sh
tail -f logs/daily-ai-infra-*.log   # 另开终端看日志
```

成功的尾行应包含 `MAIL SENT`。

### 6. 装每日定时（launchd，推荐）

```bash
scripts/install-schedule.sh ai-infra-agent              # 默认每天 09:00
scripts/install-schedule.sh ai-infra-agent --at 08:30   # 自定义时间
scripts/install-schedule.sh ai-infra-agent --status     # 看状态 + 最近日志
scripts/install-schedule.sh ai-infra-agent --uninstall  # 卸载
```

装完立即试跑一次（不用等到明天）：

```bash
launchctl kickstart -p gui/$(id -u)/local.ai-infra-agent
```

**为什么用 launchd 不用 crontab**：

| | crontab | launchd |
|---|---|---|
| 权限 | 需手动给 `/usr/sbin/cron` 开 Full Disk Access，否则 Claude CLI 读不到 `~/.claude/` | 以登录会话身份运行，天然有权限 |
| 睡眠 | 到点机器在睡 → **这一次直接丢掉** | 唤醒后补跑 |
| 路径 | 必须写绝对路径 | plist 里带 `WorkingDirectory` |

> crontab 不推荐（睡眠会丢触发、需要 Full Disk Access），但要用的话入口是 `ai-infra-agent/run.sh`。

**⚠️ 前提：机器当时得是开机/唤醒状态，且 Clash 代理在跑。** 合盖睡眠时 launchd 会等到唤醒才补跑；
代理没起时 cron 脚本的预检会直接告警退出（不会静默失败）。

### 7. 完成

明天 09:00 自动触发，日志落 `logs/daily-ai-infra-YYYYMMDD-HHMMSS.log`。

## 自定义

### 改触发时间

编辑 crontab 行的 cron 表达式：

```bash
scripts/install-schedule.sh ai-infra-agent --at 08:30
```

### 增删抓取源

编辑 `ai-infra-agent/config/repos.json`（机器可读）+ `config/sources.md`（人类可读）：

- **加 GitHub 仓**：往 `config/repos.json` 的 `tracked` 加 `{"repo": "owner/name", "prs": true, "releases": true}`，
  同时在 `config/sources.md` 的核心盘摘要里记一笔（两个文件都要动）
- **加 RSS/博客**：改 `pipeline/fetch.py` 的 `BLOG_FEEDS`
- **加领域关键词**：改 `pipeline/fetch.py` 的 `ARXIV_KEYWORDS` / `HN_TERMS`
- **调拓源的相关性闸门**：改 `pipeline/discover.py` 的 `RISING_KW` / `NOISE_KW`

### 换收件人 / 多收件人

`mail.env`：

```
MAIL_TO=user1@x.com,user2@y.com
```

（`send_mail.py` 已支持逗号分隔）

### 换 SMTP 提供商

`send_mail.py` 对端口 465 走 SSL、其他端口走 STARTTLS，换提供商只改 `mail.env`，**不用改代码**。

常见 SMTP 参数速查表：

| 邮箱 | SMTP_HOST | 端口 | SMTP_PASS 取值 |
|------|-----------|------|-----------------|
| QQ 邮箱 | `smtp.qq.com` | 465 (SSL) / 587 (STARTTLS) | 授权码（非登录密码） |
| Gmail | `smtp.gmail.com` | 465 / 587 | App Password |
| 163 邮箱 | `smtp.163.com` | 465 / 994 | 客户端授权密码 |
| 阿里云企业邮 | `smtp.mxhichina.com` | 465 | 邮箱登录密码 |
| Outlook / Hotmail | `smtp.office365.com` | 587 | 账号密码或 app password |

## 文件清单

```
personal_agents/
├── .claude/skills/daily-ai-infra.md    # 流程真值（步骤 + 分类 + 预算）
├── scripts/                            # 跨 agent 共享，只有 3 个
│   ├── _env.sh                         #   PATH / 代理 / proxy_ok / run_claude
│   ├── send_mail.py                    #   通用 SMTP 发信（markdown→HTML）
│   └── install-schedule.sh             #   通用 launchd 安装器
├── ai-infra-agent/                     # 本 agent，自包含
│   ├── run.sh                          #   唯一入口（daily / --since range）
│   ├── agent.py                        #   唯一 CLI（5 个子命令）
│   ├── pipeline/
│   │   ├── paths.py                    #     路径集中解析，不依赖 cwd
│   │   ├── fetch.py                    #     核心盘抓取
│   │   ├── discover.py                 #     拓源
│   │   ├── dedup.py                    #     跨天去重（两阶段提交）
│   │   ├── fallback.py                 #     降级报告
│   │   └── stats.py                    #     阅读时间
│   ├── config/{repos.json, sources.md}
│   ├── state/{seen,pending,discover}.json
│   ├── reports/YYYY-MM-DD.md
│   └── README.md                       # 本文件
└── logs/daily-ai-infra-*.log
```

## 两条腿：核心盘 + 拓源

| | 核心盘 | 拓源 |
|---|---|---|
| 命令 | `agent.py fetch` | `agent.py discover` + Claude 的 WebSearch |
| 干什么 | 盯**已知**的 23 个仓 + arXiv + 博客 + HN/Reddit | 找**你还不知道**的项目/方向/术语 |
| 产出 | PR / Release / 论文 / 博客 / 社区各节 | 报告的「🆕 新兴方向」节（≤4 条） |
| 记忆 | `state/seen.json`（机器哈希，防重复报） | `config/sources.md`（人类可读，防重复**发现**） |

拓源三招脚本化（GitHub Trending、awesome 清单增量、新术语识别），第四招 novelty 搜索靠 Claude 判断。
新术语识别的原理：拿今天抓到的所有标题/摘要，减去 `sources.md`「已知术语」里的词——**剩下的就是信号**。

沉淀闭环：新发现 → `sources.md` 候选观察 → 连续出料 → 提升进 `repos.json` 的 `tracked` →
从此进核心盘每天抓。**覆盖面随时间自生长，不用手改代码。**

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
| `MAIL FAILED: (535, b'Login fail. ... Please use authorized code')` | QQ 场景：把 QQ 登录密码填到 `SMTP_PASS` 了，必须用授权码 |
| `MAIL FAILED: (535, b'Username and Password not accepted')` | Gmail 场景：App Password 错或没开 2FA；密码 16 位去空格 |
| `MAIL FAILED: timeout` | 本机到 SMTP 端口不通（代理/防火墙）；QQ 可试 `SMTP_PORT=587`；Gmail 在国内网可能被墙，换 QQ |
| `MAIL FAILED: (550, b'Mail content denied')` | QQ 判定正文异常（外链太多），先用短报告试；或在 QQ 邮箱里把发件地址加白名单 |
| 发送成功但收件箱没收到 | 查垃圾箱；QQ 发 Gmail 首次可能被判垃圾，将发件地址加到通讯录 |
| 日志里 `command not found: claude` | cron 没继承 PATH；检查 `run.sh` 里的 nvm PATH 导入；macOS 需要给 cron Full Disk Access |

### 报告没生成

```bash
# 手跑一次看详细输出
./ai-infra-agent/run.sh
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
crontab -l | grep -v run.sh | crontab -

# 删凭证
rm -rf ~/.config/ai-infra-agent

# 删代码（可选）
rm -rf ai-infra-agent scripts/send_mail.py \
       .claude/skills/daily-ai-infra.md
```

## 安全注意

- `mail.env` 权限必须 600，且 **不要 commit 进 git**（项目根 `.gitignore` 应包含 `mail.env`）
- App Password 泄露后立即去 Google 账号页面撤销
- 日志文件可能包含抓取到的 PR 标题等非敏感信息，但不包含邮箱密码；如要长期保留可归档
- 不要把内网 / 公司内部源加进 skill（本 agent 设计上仅消费公开源）
