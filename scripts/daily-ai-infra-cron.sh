#!/bin/bash
# 每天 09:00 自动抓取 AI infra 推理动态并邮件发送
# 由 crontab 调用，通过 claude CLI 驱动 daily-ai-infra skill

set -euo pipefail

# 加载 nvm node bin（cron 不走 .zshrc）
export NVM_DIR="$HOME/.nvm"
_nvm_default_bin="$(ls -d "$NVM_DIR/versions/node/"*/bin 2>/dev/null | sort -V | tail -1)"
[ -d "$_nvm_default_bin" ] && export PATH="$_nvm_default_bin:$PATH"

# 代理豁免：内网 + 必要的出网站点不走公司代理
export NO_PROXY="localhost,127.0.0.1,*.alipay.com,*.antfin.com,*.alibaba-inc.com,*.aliyun-inc.com,*.taobao.com"

LOG_DIR="$HOME/Projects/personal_agents/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/daily-ai-infra-$(date +%Y%m%d-%H%M%S).log"

cd "$HOME/Projects/personal_agents"

TODAY=$(date +%Y-%m-%d)

{
  echo "=== daily-ai-infra START $(date -Iseconds) ==="
  claude --print --dangerously-skip-permissions \
    -p "按照 .claude/skills/daily-ai-infra.md 中的步骤，抓取今天 (${TODAY}) 的 AI infra 推理动态，生成日报保存到 ai-infra-agent/reports/${TODAY}.md，然后调用 scripts/send_mail.py 发邮件。最后输出 PR/论文/博客/Reddit 各分类条数和邮件发送结果。"
  echo "Exit code: $?"
  echo "=== daily-ai-infra END $(date -Iseconds) ==="
} >> "$LOG_FILE" 2>&1
