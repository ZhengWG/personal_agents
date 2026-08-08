#!/bin/zsh
# daily-ai-infra 的唯一入口 —— launchd 和手工都走这里。
#
#   ai-infra-agent/run.sh                   每日日报（launchd 调的就是这条）
#   ai-infra-agent/run.sh --since 6mo       主题趋势回顾报告
#
# 降级策略（分四级，永远不空手而归）：
#   L1  claude 正常跑完                    → 完整日报，claude 自己发信
#   L2  异常退出但报告已填过内容            → 加「未完成」横幅补发
#   L3  连报告都没有，但抓取结果在          → agent.py fallback 生成原始条目报告发出
#   L4  什么都没有                         → 才发失败告警
set -uo pipefail

# 共享底座：PATH / 代理 / 证书 / proxy_ok / run_claude；同时设好 $REPO
source "${0:A:h:h}/scripts/_env.sh"
cd "$REPO" || exit 1

AGENT_DIR="${0:A:h}"
AGENT="$AGENT_DIR/agent.py"
PY=/usr/bin/python3

SINCE=""
[ "${1:-}" = "--since" ] && SINCE="${2:-}"

LOG_DIR="$REPO/logs"; mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/daily-ai-infra-$(date +%Y%m%d-%H%M%S).log"

RUN_START=$(date +%s)          # 判断产物是不是"本轮"生成的
TODAY=$(date +%Y-%m-%d)
FETCH_JSON="/tmp/ai-infra-$(date +%Y%m%d).json"
DISCOVER_JSON="/tmp/ai-infra-discover-$(date +%Y%m%d).json"

if [ -n "$SINCE" ]; then
  REPORT="$AGENT_DIR/reports/range-${SINCE}-to-${TODAY}.md"
  PROMPT="按照 .claude/skills/daily-ai-infra.md 的 range 模式，运行 ai-infra-agent/agent.py fetch --mode range --since ${SINCE}，生成 ${SINCE} 到 ${TODAY} 的【主题趋势回顾报告】（不平铺 PR：按主题聚类、以 releases 为骨架），保存到 ${REPORT}，然后 scripts/send_mail.py 发邮件。"
  WATCHDOG=2400
else
  REPORT="$AGENT_DIR/reports/${TODAY}.md"
  PROMPT="按照 .claude/skills/daily-ai-infra.md 中的步骤，抓取今天 (${TODAY}) 的 AI infra 推理动态，生成日报保存到 ${REPORT}，然后调用 scripts/send_mail.py 发邮件。最后输出预计阅读时间、各分类条数和邮件发送结果。"
  WATCHDOG=1800
fi

# --- 工具函数 ---
alert() {
  local reason="$1"
  echo "!!! daily-ai-infra FAILED: ${reason}"
  /usr/bin/osascript -e "display notification \"${reason}\" with title \"AI Infra Daily 失败\"" 2>/dev/null || true
  local f="${LOG_DIR}/.fail-${TODAY}.md"
  printf '⚠️ AI Infra Daily 失败 — %s\n\n原因：%s\n\n日志：%s\n' "$TODAY" "$reason" "$LOG_FILE" > "$f"
  $PY "${REPO}/scripts/send_mail.py" "$f" 2>/dev/null || true
}

notify() { /usr/bin/osascript -e "display notification \"$1\" with title \"AI Infra Daily 降级\"" 2>/dev/null || true; }

# 产物新鲜度：非空 **且** 本轮生成。少了后半句，上一轮留在磁盘的旧报告
# 会被误判成"本轮半成品"，重发旧内容 + 提交没报道过的条目。2026-08-07 真发生过。
fresh() {
  local f="$1" mt
  [ -s "$f" ] || return 1
  mt=$(stat -f %m "$f" 2>/dev/null || echo 0)
  [ "$mt" -ge "$RUN_START" ]
}

# 报告值不值得发：新鲜 **且** 真填过内容。Step 2.7 会先落一份全是
# 「（生成中…）」的骨架，光有骨架还不如走 L3 发几百条带链接的原始条目。
report_usable() {
  fresh "$REPORT" || return 1
  # grep -c 计数为 0 时「输出 0 且退出码非零」，不能写 `|| echo 0`（会得到 "0\n0"）
  local filled
  filled=$(grep -cE '^● |^[0-9]+\) ' "$REPORT" 2>/dev/null) || filled=0
  [ "${filled:-0}" -ge 5 ]
}

# 两阶段提交的第二阶段：报告确实送达之后，才把 pending 并进 seen.json
commit_dedup() { $PY "$AGENT" dedup --commit 2>&1 || true; }

{
  echo "=== daily-ai-infra START $(date -Iseconds) ${SINCE:+(range since $SINCE)} ==="

  if ! proxy_ok; then
    alert "代理 127.0.0.1:${PROXY_PORT} 不可达（Clash 没起？）—— claude 直连会 403"
    echo "=== daily-ai-infra END (preflight failed) $(date -Iseconds) ==="
    exit 1
  fi

  run_claude "$WATCHDOG" "$PROMPT"
  rc=$?
  echo "Exit code: ${rc}"

  # range 模式不做降级（回顾报告没有"半成品也值得发"的诉求）
  if [ -n "$SINCE" ]; then
    [ "$rc" -ne 0 ] && alert "range 报告失败（rc=${rc}）"

  elif [ "$rc" -eq 0 ] && report_usable; then
    echo "L1 正常完成（邮件由 claude 自己发出）"

  elif report_usable; then
    echo "L2 降级：报告已填过内容但 claude 异常退出 (rc=${rc})，补发"
    local_tmp="${REPORT}.tmp"
    { head -1 "$REPORT"; echo ""
      echo "📌 ⚠️ 本期为**未完成报告**"
      echo "claude 在生成过程中被中断（退出码 ${rc}）。以下是中断前已生成的部分，后面的分类可能缺失。"
      echo "抓取到的原始数据仍在 ${FETCH_JSON}，下一轮会正常恢复。"; echo ""
      tail -n +2 "$REPORT"; } > "$local_tmp" && mv "$local_tmp" "$REPORT"
    if $PY "${REPO}/scripts/send_mail.py" "$REPORT"; then
      commit_dedup; notify "已补发未完成报告"
    else
      alert "半成品报告补发失败（rc=${rc}）"
    fi

  elif fresh "$FETCH_JSON"; then
    echo "L3 降级：无可用报告，用 ${FETCH_JSON} 生成原始条目报告"
    if $PY "$AGENT" fallback --from "$FETCH_JSON" \
         ${DISCOVER_JSON:+--discover "$DISCOVER_JSON"} \
         --reason "claude 在总结阶段被中断（退出码 ${rc}）" --out "$REPORT"; then
      if $PY "${REPO}/scripts/send_mail.py" "$REPORT"; then
        commit_dedup; notify "已发降级报告（原始条目）"
      else
        alert "降级报告生成成功但发信失败（rc=${rc}）"
      fi
    else
      alert "claude 退出码 ${rc}，且降级报告也生成失败"
    fi

  else
    alert "claude 退出码 ${rc}，且没有任何可用产物（连抓取结果都没有）"
  fi

  echo "=== daily-ai-infra END $(date -Iseconds) ==="
} >> "$LOG_FILE" 2>&1
