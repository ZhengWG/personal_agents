#!/bin/zsh
# 每周四 17:00 自动生成语雀周报（由 cron 调用，claude CLI 驱动 weekly-report skill）
#
# 同 daily-ai-infra：不要 `source ~/.zshrc` 取环境 —— set -e + 交互式 oh-my-zsh 会中途
# 中断，末尾的代理 export 没设上 → claude 直连 api.anthropic.com 触发 403。改为显式自包含。
# 语雀走内网（*.antfin.com 在 NO_PROXY，不走代理）；claude 走 Clash 代理。
set -uo pipefail

REPO="$HOME/Projects/personal_tools/personal_agents"
cd "$REPO" || exit 1

LOG_DIR="$REPO/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/weekly-report-$(date +%Y%m%d-%H%M%S).log"

# --- 自包含环境 ---
export PATH="$HOME/.local/bin:$PATH"                       # claude CLI
if [ -d "$HOME/.nvm/versions/node" ]; then                 # node + 全局 yuque-cli
  export PATH="$HOME/.nvm/versions/node/$(ls "$HOME/.nvm/versions/node" | sort -V | tail -1)/bin:$PATH"
fi
PROXY_PORT="${PROXY_PORT:-7897}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:${PROXY_PORT}}"
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:${PROXY_PORT}}"
export ALL_PROXY="${ALL_PROXY:-socks5://127.0.0.1:${PROXY_PORT}}"
export NO_PROXY="localhost,127.0.0.1,*.alipay.com,*.antfin.com,*.alibaba-inc.com,*.aliyun-inc.com,*.taobao.com"
# 公司网络做 TLS 拦截：claude(node) 必须信任公司根证书，否则 SSL certificate verification failed。
# 交互式 shell 从 /etc/zshrc 拿到这个变量，但 cron/launchd 不 source，需显式设置。
CORP_CA="/Library/Application Support/starpoint/CertManager/certificate.crt"
[ -f "$CORP_CA" ] && export NODE_EXTRA_CA_CERTS="${NODE_EXTRA_CA_CERTS:-$CORP_CA}"

# --- 失败告警：本地通知（周报发语雀，不发邮件），避免静默失败 ---
alert() {
  local reason="$1"
  echo "!!! weekly-report FAILED: ${reason}"
  /usr/bin/osascript -e "display notification \"${reason}\" with title \"语雀周报 失败\"" 2>/dev/null || true
}

{
  echo "=== weekly-report START $(date -Iseconds) ==="

  # 预检：代理端口必须在监听（claude 直连会 403）
  if ! nc -z -G3 127.0.0.1 "$PROXY_PORT" 2>/dev/null; then
    alert "代理 127.0.0.1:${PROXY_PORT} 不可达（Clash 没起？）—— claude 直连会 403"
    echo "=== weekly-report END (preflight failed) $(date -Iseconds) ==="
    exit 1
  fi

  claude --print --dangerously-skip-permissions \
    -p "按照 .claude/skills/weekly-report.md 中的步骤生成本周周报并发布到语雀。当前日期: $(date +%Y-%m-%d)"
  rc=$?
  echo "Exit code: ${rc}"

  # 收尾守卫：claude 失败 → 告警（语雀登录态过期 / 403 / 超时都会落这里）
  if [ "$rc" -ne 0 ]; then
    alert "claude 退出码 ${rc}（看日志 ${LOG_FILE}：可能 403、语雀登录态、或超时）"
  fi

  echo "=== weekly-report END $(date -Iseconds) ==="
} >> "$LOG_FILE" 2>&1
