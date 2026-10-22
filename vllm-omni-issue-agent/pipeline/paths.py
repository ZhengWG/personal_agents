"""路径集中解析 + 配置加载 —— 不依赖 cwd。

launchd 起的进程 cwd 是 plist 里的 WorkingDirectory，手工跑又是别的地方。
任何模块要拼路径都从这里取，别再各自 os.getcwd()。
"""
import datetime
import json
import os

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(AGENT_DIR)          # personal_agents/

CONFIG = os.path.join(AGENT_DIR, "config", "agent.json")
STATE_DIR = os.path.join(AGENT_DIR, "state")
REPORT_DIR = os.path.join(AGENT_DIR, "reports")
ISSUE_DIR = os.path.join(STATE_DIR, "issues")

CANDIDATES = os.path.join(STATE_DIR, "candidates.json")
TRIAGE = os.path.join(STATE_DIR, "triage.json")
FIX = os.path.join(STATE_DIR, "fix.json")
POD = os.path.join(STATE_DIR, "pod.json")

# 全仓唯一的 urlopen 出口在 ai-infra-agent 里（带重试 / 限流退避），这里按文件路径借用，
# 不另写一份。
SHARED_HTTP = os.path.join(REPO_ROOT, "ai-infra-agent", "pipeline", "http.py")


def load_config():
    with open(CONFIG, encoding="utf-8") as fh:
        cfg = json.load(fh)
    for key in ("repo", "worktree_root", "local_config_dir"):
        cfg[key] = os.path.expanduser(cfg[key])
    return cfg


def local_file(cfg, name):
    return os.path.join(cfg["local_config_dir"], name)


def load_local(cfg):
    """集群细节（镜像 / 节点 / NAS / namespace），只在本机，不进仓库。"""
    path = local_file(cfg, "pod.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError:
        raise SystemExit("缺 %s —— 集群配置只放本机，格式见 vllm-omni-issue-agent/README.md"
                         % path) from None


def today():
    return datetime.date.today().isoformat()


def report_path(day):
    return os.path.join(REPORT_DIR, "%s.md" % day)


def issue_file(number):
    return os.path.join(ISSUE_DIR, "%s.md" % number)


def save_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def fix_report_path(number):
    return os.path.join(REPORT_DIR, "fix-%s.md" % number)


def load(path, default=None):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {} if default is None else default


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)
