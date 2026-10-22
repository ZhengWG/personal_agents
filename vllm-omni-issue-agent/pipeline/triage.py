"""分诊结论的落盘：Claude 每判一个 issue 调一次 `agent.py triage add`。

为什么不让 Claude 直接写 JSON：要校验（issue 在不在今天的候选里、卡数超没超上限），
而且 `--fix` 模式要从这里取默认卡数和模型，格式错一个字段就是第二天修复时才炸。
"""
from . import paths

VERDICTS = {"fix": "✅ 推荐修", "maybe": "🟡 有前提", "skip": "⛔ 不适合"}
EFFORTS = ("S", "M", "L")


def current():
    """只认和今天候选同一天的分诊，昨天的结论不能套到今天的候选上。"""
    cands = paths.load(paths.CANDIDATES)
    tri = paths.load(paths.TRIAGE)
    if not cands or tri.get("date") != cands.get("date"):
        return {}
    return tri.get("items", {})


def add(cfg, number, verdict, cards, model, effort, reason):
    cands = paths.load(paths.CANDIDATES)
    if not cands:
        raise SystemExit("还没扫描过，先跑 agent.py scan")
    numbers = {c["number"] for c in cands.get("items", [])}
    if number not in numbers:
        raise SystemExit("#%d 不在今天的候选里（%s）" % (number, paths.CANDIDATES))
    if verdict != "skip":
        if cards is None:
            raise SystemExit("verdict=%s 必须给 --cards（只跑 CPU 测试就填 0）" % verdict)
        if not 0 <= cards <= cfg["max_cards"]:
            raise SystemExit("--cards %d 超出上限 0..%d；要更多卡就判 skip 并在理由里写明"
                             % (cards, cfg["max_cards"]))
    tri = paths.load(paths.TRIAGE)
    if tri.get("date") != cands["date"]:
        tri = {"date": cands["date"], "items": {}}
    tri["items"][str(number)] = {
        "verdict": verdict,
        "cards": cards,
        "model": model,
        "effort": effort,
        "reason": reason,
    }
    paths.save(paths.TRIAGE, tri)
    return tri["items"][str(number)]


def ranked(items):
    order = {"fix": 0, "maybe": 1, "skip": 2}
    return sorted(items.items(), key=lambda kv: (order.get(kv[1]["verdict"], 9),
                                                 EFFORTS.index(kv[1]["effort"])
                                                 if kv[1].get("effort") in EFFORTS else 9,
                                                 int(kv[0])))
