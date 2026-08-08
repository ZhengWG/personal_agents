"""集中的路径解析 —— 所有模块的默认路径都从这里取。

以前每个脚本都写死相对路径（`ai-infra-agent/config/repos.json`），意味着
**必须在仓库根目录执行**，换个 cwd 就全崩。这里改成从本文件位置反推，
在哪跑都对。
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent      # ai-infra-agent/
REPO_ROOT = AGENT_DIR.parent

CONFIG_DIR = AGENT_DIR / "config"
STATE_DIR = AGENT_DIR / "state"
REPORTS_DIR = AGENT_DIR / "reports"

REPOS_JSON = CONFIG_DIR / "repos.json"
SOURCES_MD = CONFIG_DIR / "sources.md"

SEEN_JSON = STATE_DIR / "seen.json"
PENDING_JSON = STATE_DIR / "pending.json"
DISCOVER_STATE = STATE_DIR / "discover.json"

# 中间产物放这里，便于降级路径按日期找回（cron 脚本也用同一套命名）
WORK_DIR = Path(os.environ.get("AI_INFRA_WORK_DIR", "/tmp"))


def today(utc: bool = True) -> str:
    return (datetime.now(timezone.utc) if utc else datetime.now()).strftime("%Y-%m-%d")


def fetch_json(date: str | None = None) -> Path:
    d = (date or today(utc=False)).replace("-", "")
    return WORK_DIR / f"ai-infra-{d}.json"


def discover_json(date: str | None = None) -> Path:
    d = (date or today(utc=False)).replace("-", "")
    return WORK_DIR / f"ai-infra-discover-{d}.json"


def report_path(date: str | None = None) -> Path:
    return REPORTS_DIR / f"{date or today(utc=False)}.md"


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, STATE_DIR, REPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
