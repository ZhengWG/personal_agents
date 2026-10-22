"""路径集中解析 + 配置加载 —— 不依赖 cwd。

launchd 起的进程 cwd 是 plist 里的 WorkingDirectory，手工跑又是别的地方。
任何模块要拼路径都从这里取，别再各自 os.getcwd()。
"""
import json
import os

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(AGENT_DIR)          # personal_agents/

CONFIG = os.path.join(AGENT_DIR, "config", "tasks.json")
STATE_DIR = os.path.join(AGENT_DIR, "state")
REPORT_DIR = os.path.join(AGENT_DIR, "reports")
STATE_FILE = os.path.join(STATE_DIR, "last-run.json")
PLAYBOOK_DIR = os.path.join(STATE_DIR, "playbook")

_INHERITED = (
    "community_remote",
    "ant_remote",
    "community_main",
    "delta_source",
    "rc_tag_pattern",
    "playbook_ref",
    "playbook_files",
    "oss_mirror",
    "tasks",
)


def load_config():
    """读 tasks.json，把 defaults 合进每个 repo，展开 ~。

    合并是**浅合并**：repo 里写了 tasks 就整份覆盖 defaults 的 tasks，
    不做逐 task 的深合并 —— 深合并的规则没人记得住，出了问题也看不出来。
    """
    with open(CONFIG, encoding="utf-8") as fh:
        cfg = json.load(fh)

    defaults = cfg.get("defaults", {})
    cfg["worktree_root"] = os.path.expanduser(cfg.get("worktree_root", "~/.cache/vllm-rebase-agent"))

    repos = []
    for repo in cfg.get("repos", []):
        merged = dict(repo)
        for key in _INHERITED:
            if key not in merged and key in defaults:
                merged[key] = defaults[key]
        merged["repo"] = os.path.expanduser(merged["repo"])
        merged["worktree"] = os.path.join(cfg["worktree_root"], merged["name"])
        merged["playbook_dir"] = playbook_dir(merged["name"])
        repos.append(merged)
    cfg["repos"] = repos
    return cfg


def playbook_dir(repo_name):
    return os.path.join(PLAYBOOK_DIR, repo_name)


def report_path(day):
    return os.path.join(REPORT_DIR, "%s.md" % day)


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, STATE_FILE)
