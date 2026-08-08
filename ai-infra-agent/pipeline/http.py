"""共享 HTTP 层 —— 带重试的取数，所有抓取模块共用一份。

以前 fetch.py 和 discover.py 各自写了一份 `http_get`/`http_json`/`warn`，
且**一次抖动就整源丢弃**：单次 urlopen 失败 → except → warn → 返回 []。
一轮有 ~40 个串行请求，本地网络不稳时经常静默少掉几块内容，
而日志里只有一行 warning，很容易被忽略。

现在统一走这里：

- **瞬时错误自动重试**（默认 3 次，指数退避 + 抖动）：连接重置、超时、
  DNS 抽风、502/503/504/429 这类。
- **永久错误立即放弃**：404、401/403（GitHub 限流除外）、URL 拼错等，
  重试没有意义，退避只会白等。
- 429/403 带 `Retry-After` 或 GitHub 的 `X-RateLimit-Reset` 时**按服务端指定时间等**。
- 全部失败后抛出，由调用方决定是"跳过这一源"还是中断（现有代码都是跳过）。
- 走环境里的 HTTPS_PROXY（urllib 默认行为，不用额外配置）。

统计：`stats()` 返回本轮的请求/重试/失败计数，跑完打一行，
让"网络到底稳不稳"变成可观测的数字而不是靠猜。
"""

from __future__ import annotations

import json
import random
import sys
import time
import urllib.error
import urllib.request

UA = "ai-infra-agent/0.4 (+https://github.com/personal-agents)"

DEFAULT_RETRIES = 3
DEFAULT_TIMEOUT = 30
BACKOFF_BASE = 1.6          # 1.6s → 2.6s → 4.1s（再加抖动）
MAX_BACKOFF = 30.0

# 值得重试的 HTTP 状态码：服务端临时问题 / 限流
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}

_counters = {"requests": 0, "retries": 0, "failures": 0, "waited": 0.0}


def warn(msg: str) -> None:
    print(f"[http] {msg}", file=sys.stderr)


def stats() -> dict:
    return dict(_counters)


def stats_line() -> str:
    c = _counters
    return (f"请求 {c['requests']} 次，重试 {c['retries']} 次，"
            f"放弃 {c['failures']} 次，退避累计 {c['waited']:.1f}s")


def _retry_after(e: urllib.error.HTTPError) -> float | None:
    """服务端明确说了等多久就听它的，别自己拍脑袋。"""
    # 用 `is not None` 而不是真值判断：headers 对象为空时布尔值是 False，
    # 会把服务端明确给出的 Retry-After 一起跳过。
    hdrs = e.headers if e.headers is not None else {}
    ra = hdrs.get("Retry-After")
    if ra:
        try:
            return min(float(ra), 120.0)
        except ValueError:
            pass
    reset = hdrs.get("X-RateLimit-Reset")
    if reset:
        try:
            delta = float(reset) - time.time()
            if 0 < delta <= 120:
                return delta
        except ValueError:
            pass
    return None


def _transient(e: BaseException) -> bool:
    if isinstance(e, urllib.error.HTTPError):
        # GitHub 未认证限流会返回 403 且带 X-RateLimit-Reset —— 那是可重试的
        if e.code == 403 and e.headers is not None and e.headers.get("X-RateLimit-Reset"):
            return True
        return e.code in RETRY_STATUS
    if isinstance(e, urllib.error.URLError):
        return True          # 连不上 / DNS / 超时，都值得再试
    return isinstance(e, (TimeoutError, ConnectionError, OSError))


def get(url: str, headers: dict | None = None, timeout: int = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES, label: str = "") -> bytes:
    """取 URL，瞬时失败自动重试；重试用尽后抛出最后一个异常。"""
    tag = label or url[:70]
    last: BaseException | None = None
    for attempt in range(1, retries + 1):
        _counters["requests"] += 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:   # 走环境代理
                return r.read()
        except BaseException as e:  # noqa: BLE001
            last = e
            if attempt >= retries or not _transient(e):
                break
            delay = None
            if isinstance(e, urllib.error.HTTPError):
                delay = _retry_after(e)
            if delay is None:
                delay = min(BACKOFF_BASE ** attempt, MAX_BACKOFF)
            delay += random.uniform(0, 0.4)       # 抖动，避免多源同时重试撞一起
            _counters["retries"] += 1
            _counters["waited"] += delay
            warn(f"{tag} 第 {attempt}/{retries} 次失败（{type(e).__name__}: {e}），"
                 f"{delay:.1f}s 后重试")
            time.sleep(delay)
    _counters["failures"] += 1
    raise last if last else RuntimeError(f"{tag}: unknown failure")


def get_json(url: str, headers: dict | None = None, **kw) -> object:
    return json.loads(get(url, headers, **kw))
