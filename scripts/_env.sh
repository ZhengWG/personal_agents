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

# --- ossutil（vllm-rebase 的 OSS 镜像同步要用）---
# 它装在 /usr/local/bin，而 launchd 给的 PATH 实测只有
#   /usr/bin:/bin:/usr/sbin:/sbin
# —— 没有 /usr/local/bin。上面那段 node 探测是「有 node 才加该目录」，node 在
# homebrew，所以 /usr/local/bin 一直没被加进来。少这一段，agent.py mirror 每轮
# 都以 FileNotFoundError: 'ossutil' 失败：2026-10-23 起连续三轮一个包都没传成，
# 而 CI 那边只报「OSS 镜像缺包」，两边对不上，拖到 10-26 才查出来。
for _d in /usr/local/bin /opt/homebrew/bin; do
  [ -x "$_d/ossutil" ] && export PATH="$_d:$PATH" && break
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

# --- GitHub token（可选，所有 agent 共用）---
# 有了它 API 额度从每小时 60 次变成 5000 次。只放不勾任何权限的 fine-grained token。
# 用之前先试一次：坏 token 比没有还糟 —— 每个请求都 401/403，而未认证至少能读公开仓库。
# 实际撞上过：vllm-project 和 sgl-project（LMSYS）都拒绝有效期超过 366 天的 fine-grained token，
# 而 token 一年内必然过期，过期那天不能让三个 agent 一起挂。
GITHUB_ENV_FILE="$HOME/.config/personal-agents/github.env"
if [ -f "$GITHUB_ENV_FILE" ]; then
  set -a; source "$GITHUB_ENV_FILE"; set +a
  _gh_code=$(curl -sS -m 15 -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer ${GITHUB_TOKEN:-}" https://api.github.com/repos/vllm-project/vllm 2>/dev/null)
  if [ "$_gh_code" != "200" ]; then
    echo "[_env] GITHUB_TOKEN 不可用（HTTP ${_gh_code:-?}：过期，或有效期超过 366 天被组织拒绝），本轮按未认证跑" >&2
    unset GITHUB_TOKEN
  fi
  unset _gh_code
fi

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
    # 取消看门狗要先杀 sleep、再杀子 shell。只 kill "$wd" 的话 sleep 会被
    # init 收养（PPID=1）继续跑满 secs 秒 —— claude 秒级失败时就留下一个
    # sleep 3600 挂在系统上。顺序反过来不行：子 shell 先死，sleep 就没父进程
    # 可查了。sleep 被杀后 `&&` 短路，那条 kill -9 也不会执行。
    pkill -P "$wd" 2>/dev/null
    kill "$wd" 2>/dev/null
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
