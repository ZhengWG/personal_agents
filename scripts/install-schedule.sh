#!/bin/zsh
# 通用 launchd 定时安装器 —— 任何 agent 都能用，不写死某个 agent。
#
#   scripts/install-schedule.sh <agent目录>              装到默认 09:00
#   scripts/install-schedule.sh ai-infra-agent --at 08:30
#   scripts/install-schedule.sh ai-infra-agent --status
#   scripts/install-schedule.sh ai-infra-agent --uninstall
#
# 约定：<agent目录>/run.sh 是该 agent 的入口。label = local.<agent目录名>。
#
# 为什么用 launchd 而不是 crontab：
#   1. macOS 的 cron 需要给 /usr/sbin/cron 开 Full Disk Access，否则读不到 ~/.claude/ 凭证；
#      launchd agent 以登录会话身份跑，天然有权限。
#   2. 到点时机器在睡眠 → cron **直接丢掉这一次**；launchd 会在唤醒后补跑。
#   3. launchd 原生管 stdout/stderr 重定向和失败退出码。
set -uo pipefail

REPO="${0:A:h:h}"
HOUR=9; MINUTE=0; ACTION="install"; AGENT=""

while [ $# -gt 0 ]; do
  case "$1" in
    --at)        HOUR="${2%%:*}"; MINUTE="${2##*:}"
                 HOUR="${HOUR#0}"; MINUTE="${MINUTE#0}"
                 HOUR="${HOUR:-0}"; MINUTE="${MINUTE:-0}"; shift 2 ;;
    --uninstall) ACTION="uninstall"; shift ;;
    --status)    ACTION="status"; shift ;;
    -*)          echo "未知参数: $1" >&2; exit 2 ;;
    *)           AGENT="${1%/}"; shift ;;
  esac
done

[ -n "$AGENT" ] || { echo "用法: $0 <agent目录> [--at HH:MM|--status|--uninstall]" >&2; exit 2; }

NAME="$(basename "$AGENT")"
LABEL="local.${NAME}"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
RUNNER="$REPO/$AGENT/run.sh"

case "$ACTION" in
  uninstall)
    launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null
    rm -f "$PLIST"
    echo "已卸载 ${LABEL}"
    exit 0 ;;
  status)
    [ -f "$PLIST" ] || { echo "未安装（$PLIST 不存在）"; exit 1; }
    echo "plist: $PLIST"
    launchctl print "gui/$(id -u)/${LABEL}" 2>/dev/null \
      | grep -E 'state|runs|last exit|program' || echo "（未加载）"
    echo "\n最近日志："
    ls -t "$REPO"/logs/*.log 2>/dev/null | head -3 || echo "（还没跑过）"
    exit 0 ;;
esac

[ -f "$RUNNER" ] || { echo "找不到入口 $RUNNER（约定：<agent目录>/run.sh）" >&2; exit 1; }
chmod +x "$RUNNER"
[ -f "$HOME/.config/ai-infra-agent/mail.env" ] \
  || echo "⚠️  ~/.config/ai-infra-agent/mail.env 不存在——装完也发不出邮件"
command -v claude >/dev/null 2>&1 \
  || echo "⚠️  PATH 里没有 claude CLI（run.sh 会自己加 ~/.local/bin，但先确认装过）"

mkdir -p "$HOME/Library/LaunchAgents" "$REPO/logs"

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>${RUNNER}</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>${HOUR}</integer>
    <key>Minute</key><integer>${MINUTE}</integer>
  </dict>
  <key>WorkingDirectory</key><string>${REPO}</string>
  <key>StandardOutPath</key><string>${REPO}/logs/${NAME}.launchd.out.log</string>
  <key>StandardErrorPath</key><string>${REPO}/logs/${NAME}.launchd.err.log</string>
  <key>RunAtLoad</key><false/>
  <key>ProcessType</key><string>Background</string>
</dict>
</plist>
PLISTEOF

launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null   # 幂等：先卸再装
launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null \
  || launchctl load "$PLIST" 2>/dev/null \
  || { echo "launchctl 加载失败，看 $PLIST" >&2; exit 1; }

printf '已安装 %s —— 每天 %02d:%02d 触发（入口 %s）\n' "$LABEL" "$HOUR" "$MINUTE" "$RUNNER"
echo "立即试跑： launchctl kickstart -p gui/$(id -u)/${LABEL}"
echo "看状态：   scripts/install-schedule.sh ${AGENT} --status"
echo "卸载：     scripts/install-schedule.sh ${AGENT} --uninstall"
