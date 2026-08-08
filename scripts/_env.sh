# 共享运行环境 —— 被各 agent 的 run.sh source（daily 和 --since range 两种模式都走它）。
#
# 为什么不 `source ~/.zshrc`：那是交互式 zshrc（oh-my-zsh 等），在非交互 shell 下会中途
# 中断，导致后面的 export 没设上，claude 直连 api.anthropic.com 触发 403。所以显式自包含。
#
# 本文件只设环境、不执行业务逻辑，也不 set -e（由调用方决定）。

# 仓库根 = 本文件所在目录的上一级。zsh 里 source 时 $0 就是被 source 的文件路径。
REPO="${0:A:h:h}"

# --- claude CLI ---
export PATH="$HOME/.local/bin:$PATH"

# --- node（npm 全局包要用；当前没有 agent 依赖它，留着给以后加的 agent）---
# 本机可能用 nvm 也可能用 Homebrew，按存在与否探测，不假设某一种。
# 注意 launchd/cron 的默认 PATH 只有 /bin:/usr/bin:/usr/ucb:/usr/local/bin，
# 不含 /opt/homebrew/bin —— 不显式加就是 command not found。
if [ -d "$HOME/.nvm/versions/node" ]; then
  export PATH="$HOME/.nvm/versions/node/$(ls "$HOME/.nvm/versions/node" | sort -V | tail -1)/bin:$PATH"
fi
for _d in /opt/homebrew/bin /usr/local/bin; do
  [ -x "$_d/node" ] && export PATH="$_d:$PATH"
done
unset _d

# --- 代理 ---
# 本区域直连 claude API 会 403，必须走本地 Clash。交互式 shell 里并没有设这些变量，
# 所以这里是唯一来源，不是"补一份"。
PROXY_PORT="${PROXY_PORT:-7897}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:${PROXY_PORT}}"
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:${PROXY_PORT}}"
export ALL_PROXY="${ALL_PROXY:-socks5://127.0.0.1:${PROXY_PORT}}"
# 内网域名不走代理。当前没有 agent 访问内网，这几条是给以后留的，无害。
export NO_PROXY="localhost,127.0.0.1,*.alipay.com,*.antfin.com,*.alibaba-inc.com,*.aliyun-inc.com,*.taobao.com"

# --- 公司网络的 TLS 拦截 ---
# 装了 starpoint CertManager 的公司机器上，node 必须信任公司根证书，否则
# SSL certificate verification failed。没装的机器（本机就是）走不到这行，属正常。
CORP_CA="/Library/Application Support/starpoint/CertManager/certificate.crt"
[ -f "$CORP_CA" ] && export NODE_EXTRA_CA_CERTS="${NODE_EXTRA_CA_CERTS:-$CORP_CA}"

# --- 代理预检 ---
# 返回 0 = 通。调用方自己决定失败时怎么告警（发邮件 / 弹通知 / 直接退出）。
proxy_ok() { nc -z -G3 127.0.0.1 "$PROXY_PORT" 2>/dev/null; }

# --- 带看门狗跑 claude ---
# 不用 `timeout`：那是 Homebrew coreutils 的命令，launchd 的干净 PATH 里没有。
# 用法：run_claude <超时秒数> <prompt>；返回 claude 的退出码。
# 瞬时网络错误 —— 重试有意义。**故意不含** session limit（等几十秒没用）
# 和看门狗 kill（rc=137，重试只会再挂一次）。
CLAUDE_RETRYABLE='ECONNRESET|ETIMEDOUT|EPIPE|socket hang up|Unable to connect to API|fetch failed|network error'

run_claude() {
  local secs="$1" prompt="$2" out rc attempt
  out="$(mktemp -t runclaude)" || return 1
  for attempt in 1 2; do
    claude --print --dangerously-skip-permissions -p "$prompt" > "$out" 2>&1 &
    local cp=$!
    # 用 `&&` 而不是 `;`：这样杀掉 sleep（想提前取消看门狗）不会误触发 kill。
    # 写成 `;` 时 sleep 一退出，子 shell 就立刻执行下一条 kill -9，等于把
    # "取消看门狗"变成"立即处决"。要延长超时请改 secs 后重跑，别杀 sleep。
    ( sleep "$secs" && kill -9 "$cp" 2>/dev/null ) &
    local wd=$!
    wait "$cp"; rc=$?
    kill "$wd" 2>/dev/null    # 杀子 shell 本身；孤儿 sleep 自己会退，不会再 kill
    cat "$out"
    [ "$rc" -eq 0 ] && break
    if [ "$attempt" -eq 1 ] && grep -qiE "$CLAUDE_RETRYABLE" "$out"; then
      echo "[run_claude] 检测到瞬时网络错误（rc=${rc}），60 秒后重试一次"
      sleep 60
      continue
    fi
    break
  done
  rm -f "$out"
  return $rc
}
