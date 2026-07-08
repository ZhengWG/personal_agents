#!/bin/zsh
# 按需生成 AI infra 推理报告（手动调用）。
#   scripts/ai-infra-report.sh                  # daily 日报（同 cron）
#   scripts/ai-infra-report.sh --since 6mo       # 近半年主题趋势回顾
#   scripts/ai-infra-report.sh --since 1y        # 近一年
#   scripts/ai-infra-report.sh --since 2026-01-01
#
# 与 daily-ai-infra-cron.sh 共用同一套自包含环境（显式代理，不 source 交互 zshrc）。
set -uo pipefail

REPO="$HOME/Projects/personal_tools/personal_agents"
cd "$REPO" || exit 1

SINCE=""
if [ "${1:-}" = "--since" ]; then SINCE="${2:-}"; fi

# --- 自包含环境 ---
export PATH="$HOME/.local/bin:$PATH"
if [ -d "$HOME/.nvm/versions/node" ]; then
  export PATH="$HOME/.nvm/versions/node/$(ls "$HOME/.nvm/versions/node" | sort -V | tail -1)/bin:$PATH"
fi
PROXY_PORT="${PROXY_PORT:-7897}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:${PROXY_PORT}}"
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:${PROXY_PORT}}"
export ALL_PROXY="${ALL_PROXY:-socks5://127.0.0.1:${PROXY_PORT}}"
export NO_PROXY="localhost,127.0.0.1,*.alipay.com,*.antfin.com,*.alibaba-inc.com,*.aliyun-inc.com,*.taobao.com"
# 公司网络做 TLS 拦截：claude(node) 必须信任公司根证书，否则 SSL certificate verification failed。
CORP_CA="/Library/Application Support/starpoint/CertManager/certificate.crt"
[ -f "$CORP_CA" ] && export NODE_EXTRA_CA_CERTS="${NODE_EXTRA_CA_CERTS:-$CORP_CA}"

if ! nc -z -G3 127.0.0.1 "$PROXY_PORT" 2>/dev/null; then
  echo "代理 127.0.0.1:${PROXY_PORT} 不可达 —— 先开 Clash 再跑（否则 claude 会 403）" >&2
  exit 1
fi

TODAY=$(date +%Y-%m-%d)
if [ -n "$SINCE" ]; then
  REPORT="$REPO/ai-infra-agent/reports/range-${SINCE}-to-${TODAY}.md"
  PROMPT="按照 .claude/skills/daily-ai-infra.md 的 range 模式，运行 fetch_sources.py --mode range --since ${SINCE}，生成一份从 ${SINCE} 到 ${TODAY} 的 AI infra 推理【主题趋势回顾报告】（不要平铺 PR：按主题聚类、以 releases 为骨架、代表性条目即可），保存到 ${REPORT}，然后调用 scripts/send_mail.py 发邮件。最后汇报各主题与邮件结果。"
  echo "mode=range  since=${SINCE}  report=${REPORT}"
else
  REPORT="$REPO/ai-infra-agent/reports/${TODAY}.md"
  PROMPT="按照 .claude/skills/daily-ai-infra.md 的 daily 模式，生成今天 (${TODAY}) 的 AI infra 推理日报到 ${REPORT}，然后调用 scripts/send_mail.py 发邮件。最后汇报各分类条数与邮件结果。"
  echo "mode=daily  report=${REPORT}"
fi

claude --print --dangerously-skip-permissions -p "$PROMPT"
