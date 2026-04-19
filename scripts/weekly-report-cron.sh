#!/bin/bash
# 每周四 17:00 自动生成语雀周报
# 由 crontab 调用，通过 claude CLI 执行 skill

set -euo pipefail

# 加载 nvm 环境（cron 不会 source .zshrc）
export NVM_DIR="$HOME/.nvm"
_nvm_default_bin="$(ls -d "$NVM_DIR/versions/node/"*/bin 2>/dev/null | sort -V | tail -1)"
[ -d "$_nvm_default_bin" ] && export PATH="$_nvm_default_bin:$PATH"

# 绕过代理（语雀是内网）
export NO_PROXY="localhost,127.0.0.1,*.alipay.com,*.antfin.com,*.alibaba-inc.com,*.aliyun-inc.com,*.taobao.com"

LOG_DIR="$HOME/Projects/personal_agents/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/weekly-report-$(date +%Y%m%d-%H%M%S).log"

cd "$HOME/Projects/personal_agents"

claude --print --dangerously-skip-permissions -p "按照 .claude/skills/weekly-report.md 中的步骤生成本周周报并发布到语雀。当前日期: $(date +%Y-%m-%d)" \
  >> "$LOG_FILE" 2>&1

echo "Exit code: $?" >> "$LOG_FILE"
