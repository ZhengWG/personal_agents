#!/bin/zsh
# vllm-omni-issue-agent 的唯一入口 —— launchd 和手工都走这里。
#
#   vllm-omni-issue-agent/run.sh                         每日分诊（launchd 调的就是这条）
#   vllm-omni-issue-agent/run.sh --fix 9242              手动修一个 issue（卡数按分诊结论，没有就 1）
#   vllm-omni-issue-agent/run.sh --fix 9242 --cards 2    指定卡数（上限见 config/agent.json）
#   vllm-omni-issue-agent/run.sh --fix 9242 --keep-pod   修完放卡但留着 pod，方便接着手工调
#
# 分诊：agent.py 搜社区新 bug、判断有没有人在做 → Claude 读 issue 和代码判断值不值得修、
#       要几张卡 → 报告 + macOS 通知。不起 pod、不改代码。
# 修复：agent.py 开本地分支 + 隔离 worktree → Claude 起 pod 占卡、拉模型装环境、复现、修、
#       测 → 只提交到本地分支。**不推送、不在 GitHub 上评论或开 PR。**
#
# 降级：
#   L1  全部跑完                         → 完整报告
#   L2  机械部分跑完，代理不通 / Claude 挂了 → 只有事实的清单，通知里说明
#   L3  agent.py 自己失败                 → 告警通知 + 日志
set -uo pipefail

source "${0:A:h:h}/scripts/_env.sh"      # 共享底座：PATH / 代理 / proxy_ok / run_claude；同时设好 $REPO
cd "$REPO" || exit 1

AGENT_DIR="${0:A:h}"
AGENT="$AGENT_DIR/agent.py"
PY=/usr/bin/python3
SKILL=".claude/skills/vllm-omni-issue.md"
# 分诊要逐个读十来个 issue 再去代码里找落点，量级和 ai-infra 的拓源差不多。
TRIAGE_WATCHDOG=2700
# 修复含装环境（vllm 版本对不上要现装）+ 拉模型 + 复现 + 修 + 回归测试，卡全程占着。
# 被 kill 时 trap 会删 pod 放卡，本地分支和 worktree 留着，可以 --fix 同一个号接着做。
FIX_WATCHDOG=7200

FIX=""; CARDS=""; KEEP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --fix)      FIX="$2"; shift 2 ;;
    --cards)    CARDS="$2"; shift 2 ;;
    --keep-pod) KEEP=1; shift ;;
    *)          echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

TODAY=$(date +%Y-%m-%d)
LOG_DIR="$REPO/logs"; mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/vllm-omni-issue-$(date +%Y%m%d-%H%M%S).log"
export OMNI_ISSUE_OWNER="run-$$"        # 修复会话的占用者，防两个 --fix 同时跑

_T0=$(date +%s)
stamp() { printf '[%s +%ds] %s\n' "$(date +%H:%M:%S)" "$(( $(date +%s) - _T0 ))" "$*"; }

triage() {
  local report="$AGENT_DIR/reports/${TODAY}.md"
  echo "=== vllm-omni-issue triage START $(date -Iseconds) ==="

  stamp "扫描开始"
  $PY "$AGENT" scan
  local rc=$?
  stamp "扫描结束 exit=${rc}"
  if [ "$rc" -ne 0 ]; then
    echo "L3：扫描失败"
    $PY "$AGENT" notify --message "扫描失败（rc=${rc}），看 ${LOG_FILE}"
    return 1
  fi

  local n
  n=$($PY "$AGENT" status --unclaimed)
  if [ "${n:-0}" -eq 0 ]; then
    echo "L1：没有未认领的 bug，不劳烦 claude"
    $PY "$AGENT" notify
    return 0
  fi

  if ! proxy_ok; then
    echo "L2：代理 127.0.0.1:${PROXY_PORT} 不通，claude 跑不了，只发事实清单"
    $PY "$AGENT" notify --message "未认领 ${n} 个，代理不通没做分诊：${report}"
    return 0
  fi

  local prompt="按照 ${SKILL} 的「每日分诊」流程处理今天的候选。输入是 ${AGENT_DIR}/state/candidates.json；每个结论用 agent.py triage add 落盘，最后把分析写进 ${report} 的「分析」一节。只读：不要建分支、不要起 pod、不要改任何仓库。"
  stamp "claude 分诊开始（看门狗 ${TRIAGE_WATCHDOG}s）"
  run_claude "$TRIAGE_WATCHDOG" "$prompt"
  local crc=$?
  stamp "claude 分诊结束 exit=${crc}"

  $PY "$AGENT" render >/dev/null 2>&1 || true
  if [ "$crc" -eq 0 ]; then
    echo "L1：分诊完成"
    $PY "$AGENT" notify
  else
    echo "L2：claude 中途失败（rc=${crc}）"
    $PY "$AGENT" notify --message "未认领 ${n} 个，分诊中断(rc=${crc})，清单仍可看：${report}"
  fi
  echo "=== vllm-omni-issue triage END $(date -Iseconds) ==="
}

# 不管 claude 怎么结束（正常 / 看门狗 kill / Ctrl-C），卡都要放掉。
cleanup_pod() {
  [ -n "${_CLEANED:-}" ] && return
  _CLEANED=1
  if [ "$KEEP" -eq 1 ]; then
    stamp "放卡，pod 留着（--keep-pod）"
    $PY "$AGENT" pod down --keep || true
  else
    stamp "删 pod"
    $PY "$AGENT" pod down || true
  fi
}

fix() {
  echo "=== vllm-omni-issue fix #${FIX} START $(date -Iseconds) ==="

  # 上一轮崩溃留下的、本 agent 建的对象先清掉（记录在案的那个留给 pod up 复用）
  $PY "$AGENT" pod down --stale || true

  stamp "开分支"
  if ! $PY "$AGENT" fix start "$FIX"; then
    echo "L3：开分支失败"
    $PY "$AGENT" notify --fix "$FIX" --message "开分支失败，看 ${LOG_FILE}"
    return 1
  fi
  if ! proxy_ok; then
    echo "L3：代理不通，claude 跑不了"
    $PY "$AGENT" notify --fix "$FIX" --message "代理 127.0.0.1:${PROXY_PORT} 不通，没开始修"
    return 1
  fi

  trap cleanup_pod EXIT INT TERM
  local cards_hint="${CARDS:-按分诊结论（state/triage.json）定，没有就先 1 张}"
  local prompt="按照 ${SKILL} 的「修复」流程处理 issue #${FIX}。会话在 ${AGENT_DIR}/state/fix.json（分支、worktree），issue 全文在 ${AGENT_DIR}/state/issues/${FIX}.md。卡数：${cards_hint}，上限见 config/agent.json 的 max_cards。先复现、再修、再写回归测试；只提交到本地分支（agent.py fix commit），修复报告写到 ${AGENT_DIR}/reports/fix-${FIX}.md。不要 push，不要在 GitHub 上评论或开 PR，不要动主 checkout。"
  stamp "claude 修复开始（看门狗 ${FIX_WATCHDOG}s）"
  run_claude "$FIX_WATCHDOG" "$prompt"
  local crc=$?
  stamp "claude 修复结束 exit=${crc}"
  cleanup_pod
  trap - EXIT INT TERM

  local summary
  summary=$($PY -c "
import sys; sys.path.insert(0, '${AGENT_DIR}')
from pipeline import fix, paths
s = fix.summary(paths.load_config())
print('%d 个提交，%s' % (len(s['commits']), '报告 ' + s['report'] if s['report'] else '没写报告'))
" 2>/dev/null || echo "状态未知")
  echo "结果：${summary}"
  if [ "$crc" -eq 0 ]; then
    $PY "$AGENT" notify --fix "$FIX" --message "$summary"
  else
    $PY "$AGENT" notify --fix "$FIX" --message "中断(rc=${crc})：${summary}；分支和 worktree 都留着，再 --fix ${FIX} 可接着做"
  fi
  echo "=== vllm-omni-issue fix #${FIX} END $(date -Iseconds) ==="
}

if [ -z "$FIX" ]; then
  triage >> "$LOG_FILE" 2>&1
else
  # 手动跑的，同时打到终端
  fix 2>&1 | tee -a "$LOG_FILE"
fi
