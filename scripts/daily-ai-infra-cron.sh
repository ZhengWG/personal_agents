#!/bin/zsh
# 每天 09:00 自动抓取 AI infra 推理动态并邮件发送
# 由 cron/launchd 调用，通过 claude CLI 驱动 daily-ai-infra skill
#
# 注意：不要 `source ~/.zshrc` 来取环境 —— 那是交互式 zshrc（oh-my-zsh 等），
# 在 `set -e` 的非交互 shell 下会中途中断，导致末尾的代理 export 没设上，
# claude 直连 api.anthropic.com 触发 `403 Request not allowed`。这里改为显式自包含设置。
set -uo pipefail

REPO="$HOME/Projects/personal_tools/personal_agents"
cd "$REPO" || exit 1

LOG_DIR="$REPO/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/daily-ai-infra-$(date +%Y%m%d-%H%M%S).log"

TODAY=$(date +%Y-%m-%d)
REPORT="$REPO/ai-infra-agent/reports/${TODAY}.md"

# --- 自包含环境 ---
export PATH="$HOME/.local/bin:$PATH"                       # claude CLI
if [ -d "$HOME/.nvm/versions/node" ]; then                 # node（若 skill 用到）
  export PATH="$HOME/.nvm/versions/node/$(ls "$HOME/.nvm/versions/node" | sort -V | tail -1)/bin:$PATH"
fi
# 走本地 Clash 代理破区域限制（本区域直连 claude API 会 403）。
PROXY_PORT="${PROXY_PORT:-7897}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:${PROXY_PORT}}"
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:${PROXY_PORT}}"
export ALL_PROXY="${ALL_PROXY:-socks5://127.0.0.1:${PROXY_PORT}}"
# 内网 + 必要出网站点不走代理
export NO_PROXY="localhost,127.0.0.1,*.alipay.com,*.antfin.com,*.alibaba-inc.com,*.aliyun-inc.com,*.taobao.com"
# 公司网络做 TLS 拦截：claude(node) 必须信任公司根证书，否则 SSL certificate verification failed。
# 交互式 shell 从 /etc/zshrc 拿到这个变量，但 cron/launchd 不 source，需显式设置。
CORP_CA="/Library/Application Support/starpoint/CertManager/certificate.crt"
[ -f "$CORP_CA" ] && export NODE_EXTRA_CA_CERTS="${NODE_EXTRA_CA_CERTS:-$CORP_CA}"

# --- 失败告警：本地通知（不依赖网络）+ 尽力发邮件，避免静默失败 ---
alert() {
  local reason="$1"
  echo "!!! daily-ai-infra FAILED: ${reason}"
  /usr/bin/osascript -e "display notification \"${reason}\" with title \"AI Infra Daily 失败\"" 2>/dev/null || true
  local f="${LOG_DIR}/.fail-${TODAY}.md"
  printf '⚠️ AI Infra Daily 失败 — %s\n\n原因：%s\n\n日志：%s\n' "$TODAY" "$reason" "$LOG_FILE" > "$f"
  /usr/bin/python3 "${REPO}/scripts/send_mail.py" "$f" 2>/dev/null || true
}

{
  echo "=== daily-ai-infra START $(date -Iseconds) ==="

  # 预检：代理端口必须在监听（最常见失败 = Clash 没起 → claude 直连 403）
  if ! nc -z -G3 127.0.0.1 "$PROXY_PORT" 2>/dev/null; then
    alert "代理 127.0.0.1:${PROXY_PORT} 不可达（Clash 没起？）—— claude 直连会 403"
    echo "=== daily-ai-infra END (preflight failed) $(date -Iseconds) ==="
    exit 1
  fi

  # 看门狗：claude 卡死 / 网络反复 ECONNRESET 重连时，最多 20 分钟就杀掉，避免挂死数小时
  claude --print --dangerously-skip-permissions \
    -p "按照 .claude/skills/daily-ai-infra.md 中的步骤，抓取今天 (${TODAY}) 的 AI infra 推理动态，生成日报保存到 ${REPORT}，然后调用 scripts/send_mail.py 发邮件。最后输出 PR/论文/博客/Reddit 各分类条数和邮件发送结果。" &
  CLAUDE_PID=$!
  ( sleep 1200; kill -9 "$CLAUDE_PID" 2>/dev/null ) &
  WD_PID=$!
  wait "$CLAUDE_PID"; rc=$?
  kill "$WD_PID" 2>/dev/null
  echo "Exit code: ${rc}"

  # 收尾守卫：claude 失败 或 报告没生成 → 告警
  if [ "$rc" -ne 0 ]; then
    alert "claude 退出码 ${rc}（可能 403/超时，看日志 ${LOG_FILE}）"
  elif [ ! -s "$REPORT" ]; then
    alert "claude 跑完但没生成报告 ${REPORT}"
  fi

  echo "=== daily-ai-infra END $(date -Iseconds) ==="
} >> "$LOG_FILE" 2>&1
