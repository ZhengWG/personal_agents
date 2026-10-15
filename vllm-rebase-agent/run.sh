#!/bin/zsh
# vllm-rebase-agent 的唯一入口 —— launchd 和手工都走这里。
#
#   vllm-rebase-agent/run.sh                       跑全部仓库（launchd 调的就是这条）
#   vllm-rebase-agent/run.sh --repo vllm-ant       只跑一个仓库
#   vllm-rebase-agent/run.sh --no-fetch            不抓远端（调试）
#
# 分工：agent.py 只做机械动作（抓远端 / 隔离 worktree / 演练 merge+rebase / 记冲突），
# claude 只做判断（按仓库自带的 ant-release-rebase skill 解释每个冲突该怎么解）。
#
# 降级策略（三级，永远留下点东西）：
#   L1  agent.py 跑完 + claude 写完分析      → 完整报告
#   L2  agent.py 跑完，claude 没跑/挂了       → 只有事实的报告，通知里说明分析缺失
#   L3  agent.py 自己就失败了                 → 告警通知 + 日志
set -uo pipefail

source "${0:A:h:h}/scripts/_env.sh"
export VLLM_REBASE_OWNER="launchd-$$"     # resolve 会话租约的占用者标签，和手工操作区分开      # 共享底座：PATH / 代理 / proxy_ok / run_claude；同时设好 $REPO
cd "$REPO" || exit 1

AGENT_DIR="${0:A:h}"
AGENT="$AGENT_DIR/agent.py"
PY=/usr/bin/python3
SKILL=".claude/skills/vllm-rebase.md"
# 解冲突比单纯写分析慢得多（omni 一轮可能 8 个冲突，每个都要去上游 grep 复核），
# 1800 秒不够用，实测会在半路被看门狗 kill 掉，留下一棵解了一半的树。
WATCHDOG=3600

TODAY=$(date +%Y-%m-%d)
REPORT="$AGENT_DIR/reports/${TODAY}.md"
LOG_DIR="$REPO/logs"; mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/vllm-rebase-$(date +%Y%m%d-%H%M%S).log"

notify() { /usr/bin/osascript -e "display notification \"$2\" with title \"$1\"" 2>/dev/null || true; }

# 阶段计时。2026-10-14 那轮 START→END 用了 58 分钟，但日志里两点之间什么都没有，
# 分不清是机械重放慢还是 claude 慢（当天 claude 其实是秒级失败的）。
_T0=$(date +%s)
stamp() { printf '[%s +%ds] %s\n' "$(date +%H:%M:%S)" "$(( $(date +%s) - _T0 ))" "$*"; }

{
  echo "=== vllm-rebase START $(date -Iseconds) args=$* ==="

  # 机械部分不需要 claude、也不需要代理（git 走 ssh），所以无条件先跑。
  stamp "机械重放开始"
  $PY "$AGENT" run "$@"
  rc=$?
  stamp "机械重放结束 exit=${rc}"

  if [ ! -s "$REPORT" ]; then
    echo "L3：连报告都没生成"
    notify "vLLM 每日 rebase 💥 失败" "agent.py run 没产出报告（rc=${rc}），看 ${LOG_FILE}"
    echo "=== vllm-rebase END $(date -Iseconds) ==="
    exit 1
  fi

  WORST=$($PY -c "
import sys; sys.path.insert(0, '${AGENT_DIR}')
from pipeline import paths, report
print(report.severity(paths.load_state()))
" 2>/dev/null || echo unknown)
  echo "最严重状态：${WORST}"

  if [ "$WORST" = "clean" ]; then
    echo "L1：全绿，不劳烦 claude 分析"
    $PY "$AGENT" notify
  elif ! proxy_ok; then
    echo "L2：有问题但代理 127.0.0.1:${PROXY_PORT} 不可达，claude 跑不了，只发事实报告"
    $PY "$AGENT" notify --message "有 ${WORST}，但代理不通没做分析：${REPORT}"
  else
    PROMPT="按照 ${SKILL} 的步骤处理今天这一轮。输入是 ${AGENT_DIR}/state/last-run.json 和各仓库的 playbook（${AGENT_DIR}/state/playbook/<仓库名>/）。先用 agent.py resolve 逐个解冲突（顺序：每个仓库先 tracker 再 daily 再 release），解不动的走 stop 交人工；然后 agent.py render 刷新报告事实部分；最后把判断和待人工事项写进 ${REPORT} 的「分析与建议」一节。不要 push，不要动用户的主 checkout。"
    stamp "claude 解冲突开始（看门狗 ${WATCHDOG}s）"
    run_claude "$WATCHDOG" "$PROMPT"
    crc=$?
    stamp "claude 解冲突结束 exit=${crc}"
    # claude 被看门狗 kill 时可能正停在某个冲突中间，worktree 会挂着一棵半成品树，
    # 不清掉的话第二天 resolve start 一上来就失败。abort 是幂等的，没会话时也安全。
    if [ "$crc" -ne 0 ]; then
      $PY "$AGENT" resolve abort >/dev/null 2>&1 || true
    fi

    # 推送解完冲突的候选树。只在 claude 正常收尾时做 —— 它中途被 kill 的话
    # 候选树可能只重放了一半，而 verified 还是上一次的值。
    # 不可逆的一步由脚本调，不交给 claude 自己：解冲突的和决定推不推的不该是同一个。
    # 放在 render 之前，报告里「推送」那一行才是最终结果而不是机械阶段的拒绝理由。
    if [ "$crc" -eq 0 ]; then
      stamp "推送开始"
      $PY "$AGENT" push 2>&1 || true
      stamp "推送结束"
    fi

    $PY "$AGENT" render >/dev/null 2>&1 || true

    if [ "$crc" -eq 0 ]; then
      echo "L1：解冲突 + 分析已完成"
      $PY "$AGENT" notify
    else
      echo "L2：claude 中途失败（rc=${crc}），已清理半成品 worktree"
      $PY "$AGENT" notify --message "有 ${WORST}，解冲突/分析中断(rc=${crc})，事实报告仍可看：${REPORT}"
    fi
  fi

  echo "=== vllm-rebase END $(date -Iseconds) ==="
} >> "$LOG_FILE" 2>&1
