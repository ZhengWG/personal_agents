# daily-ai-infra — AI 推理优化日报 Agent

每天固定时间（默认 09:00）自动抓取 AI infra 推理相关公开源的最新动态，用 Claude CLI 分类整理成日报，邮件发送到指定邮箱。

## 抓取源（全部公开，无需 token）

**核心盘**（`agent.py fetch`）：`config/repos.json` 里 23 个推理仓的 PR + Release（sglang / vllm /
vllm-omni / sglang-omni / TensorRT-LLM / flashinfer / dynamo / Mooncake / lmdeploy / tilelang /
TileRT / tokenspeed / DeepSeek 全家桶 / llm-d / TGI / transformers / llama.cpp）· arXiv
（cs.LG/DC/AR/PF/CL/OS，推理关键词预筛）· HuggingFace Daily Papers · HF 模型发布 ·
Hacker News（Algolia）· Reddit r/LocalLLaMA · 11 个博客 RSS ·
**LMSYS/SGLang 博客**（该站无 RSS、页面是 Next.js 前端渲染，`fetch_lmsys()` 解析其内嵌 JSON）。

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

## CLI：`agent.py`

所有数据处理都在这一个入口下，skill 里调的就是它。**在哪个目录执行都可以**
（路径由 `pipeline/paths.py` 从文件位置反推，不依赖 cwd）：

```bash
python3 ai-infra-agent/agent.py fetch --mode daily          # 核心盘 → 归一化 JSON(stdout)
python3 ai-infra-agent/agent.py fetch --mode range --since 6mo
python3 ai-infra-agent/agent.py dedup                       # 跨天去重（stdin→stdout）
python3 ai-infra-agent/agent.py dedup --commit              # 两阶段提交的第二阶段
python3 ai-infra-agent/agent.py dedup --purge-date 2026-08-07   # 运维：撤销某天的已读标记
python3 ai-infra-agent/agent.py discover --from <抓取JSON>  # 拓源
python3 ai-infra-agent/agent.py fallback --from <抓取JSON> --out <md>   # 降级报告
python3 ai-infra-agent/agent.py stats <报告> --budget 20    # 阅读时间，超预算退出码 1
```

各命令都支持 `--no-record`（只读不落状态）和 `--help`。

## 三个关键机制

这三样都是被真实故障逼出来的，改代码前先理解为什么这么设计。

### 1. 去重用两阶段提交

`dedup` **只写 `state/pending.json`，不碰 `seen.json`**；必须等报告真的发出去，
`run.sh` 或 skill 才调 `dedup --commit` 落盘。

> **为什么**：旧版在抓取阶段就标记"已读"，但报告要十几分钟后才生成。
> 中间任何崩溃（超时、限额、手滑 kill）都会造成**条目被标记已读、报告却从没产出**——
> 一整天的料被吞掉，第二天也不会再出现。2026-08-07 连炸两轮才发现。
>
> 崩在中间 → pending 被下一轮直接覆盖，`seen.json` 从未被污染。

### 2. 失败分四级降级，绝不空手而归

`run.sh` 在 claude 退出后按产物决定怎么办：

| 级别 | 条件 | 动作 |
|---|---|---|
| L1 | 退出码 0 且报告可用 | 正常，claude 自己发信 |
| L2 | 报告**已填过内容**（≥5 条） | 加「未完成」横幅补发半成品 |
| L3 | 无可用报告，但抓取 JSON 在 | `agent.py fallback` 发几百条带链接的原始条目 |
| L4 | 什么都没有 | 才发失败告警 |

两个判断细节，少了会出事：

- **`fresh()`**：产物必须是**本轮**生成的（mtime ≥ 启动时间）。少了这条，上一轮留在磁盘上的
  旧报告会被当成本轮半成品重发，还会连带提交一批没被报道过的 dedup 条目。
- **`report_usable()`**：光有 Step 2.7 落的空骨架（全是「（生成中…）」）不值得发，
  那还不如走 L3 发原始条目。

### 3. 阅读预算 ≤20 分钟，且可自检

不设限时模型会写到 175 条 / 32 分钟，其中 GitHub PR 一节独占 64%。
skill 里给了各节硬上限，写完必须跑 `agent.py stats --budget 20` 自检，超了回去砍。

## 自定义

### 改触发时间

重新装一次即可（幂等，会先卸再装）：

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

## 网络不稳

所有取数走 `pipeline/http.py`（**全仓唯一的 `urlopen` 出口**）：

| 情况 | 行为 |
|---|---|
| 连接重置 / 超时 / DNS 抽风 / 502·503·504 | 重试 3 次，指数退避 + 抖动 |
| 429、GitHub 限流（403 带 `X-RateLimit-Reset`） | 按服务端指定时间等 |
| 404 / URL 写错 | 立即放弃，不浪费退避 |

以前一次抖动就整源丢弃（`except → warn → return []`），一轮 40 个串行请求，
网络差时会静默少内容而日志里只有一行 warning。现在跑完会打
`请求 N 次，重试 M 次，放弃 K 次`，网络状况是可观测的数字。

## 排障

### 邮件没发出

```bash
# 1) 看日志
ls -t logs/daily-ai-infra-*.log | head -1 | xargs tail -80

# 2) 单独测发信
printf '📋 发信测试\n\n📌 说明\n● [链接测试](https://github.com/vllm-project/vllm)\n' > /tmp/t.md
/usr/bin/python3 scripts/send_mail.py /tmp/t.md
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
| 日志里 `command not found: claude` | launchd 的 PATH 不含 `~/.local/bin`；确认 `run.sh` 第一行 source 了 `../scripts/_env.sh` |

### 报告没生成

```bash
# 手跑一次看详细输出
./ai-infra-agent/run.sh
cat logs/daily-ai-infra-*.log | tail -200
```

- `claude --print` 卡住 → 检查 `claude auth` 是否过期
- 抓取某个源失败但整体应该继续 → skill 已容错，会跳过

### 定时没触发

```bash
scripts/install-schedule.sh ai-infra-agent --status   # 看 runs / last exit code
launchctl print gui/$(id -u)/local.ai-infra-agent     # 完整状态
log show --predicate 'process == "launchd"' --last 12h | grep ai-infra   # 系统日志
```

常见原因：机器当时关机（launchd 只在唤醒后补跑，关机期间的触发会丢）、
Clash 没起（预检会告警退出，日志里能看到）、plist 被卸载。

## 卸载

```bash
# 取消定时（launchd）
scripts/install-schedule.sh ai-infra-agent --uninstall

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
