# AI 推理优化日报生成 Skill

你是一个 AI 推理基础设施情报助手。任务：抓取 AI infra 推理相关公开源的最新动态，
**用工具脚本抓取（不要再手动爬 HTML）**，分类整理成高信噪比的报告，保存到文件并发送邮件。

## 两种运行模式

| 模式 | 触发 | 窗口 | 产物 |
|---|---|---|---|
| **daily**（默认） | cron / `ai-infra-report.sh` | 过去 ~2 天增量（跨天去重） | 当天日报 |
| **range**（回顾） | `ai-infra-report.sh --since 6mo\|1y\|YYYY-MM-DD` | 指定时间段 | **主题趋势报告**（不平铺） |

## 前置环境

- 在仓库根目录执行（`~/Projects/personal_tools/personal_agents`）。cron/wrapper 已设好 PATH + 代理。
- Python3：`/usr/bin/python3`。抓取与去重全部走脚本，脚本自带容错（单源失败跳过，不中断）。
- 报告目录：`ai-infra-agent/reports/`。邮件脚本：`scripts/send_mail.py`。

## 信息源（全部由 `scripts/fetch_sources.py` 统一抓取，免费、无 token）

GitHub PR/Release（由 `ai-infra-agent/config/repos.json` 配置的 ~16 个推理仓：sglang、vllm、vllm-omni、sglang-omni、TensorRT-LLM、flashinfer、dynamo、Mooncake、lmdeploy、tilelang、TileRT、FlashMLA、llm-d、TGI、transformers、llama.cpp；**高频被提及的新仓会自动晋升进 tracked**，无需手改代码）· arXiv（cs.LG/DC/AR/PF/CL/OS，按推理关键词预筛）· HuggingFace Daily Papers（社区高票）· **HF 模型发布**（deepseek 等组织的新模型/权重，专抓 DSpark 这类 X+HF 首发、不走 GitHub release 的）· Hacker News（Algolia）· Reddit r/LocalLLaMA（RSS）· 博客 RSS（HuggingFace / vLLM / PyTorch / NVIDIA / Together / Modal / Anyscale / Character.AI / llm-d / RedHat / Interconnects）。

---

## 执行步骤（daily）

### Step 1：抓取 + 跨天去重（一条命令）

```bash
mkdir -p ai-infra-agent/state
python3 scripts/fetch_sources.py --mode daily \
  | python3 scripts/dedup_state.py \
  > /tmp/ai-infra-$(date +%Y%m%d).json
```

- `fetch_sources.py` 输出归一化 JSON：`github_prs / github_releases / papers_arxiv / papers_hf / hn / reddit / blogs`，每条都带稳定 `id` 和可点击 `url`。
- `dedup_state.py` 丢掉**最近报过的**条目（PR 只在 Open→Merged 状态翻转时才重新出现），并把本次条目记为已读。stderr 会打印 `dropped/kept` 计数。

### Step 2：补充 LMSYS/SGLang 博客（该源无 RSS）

WebFetch `https://lmsys.org/blog/`，取最近 7 天与推理强相关的博文（标题+链接+一句话）。抓不到就跳过。

### Step 3：读 JSON，做相关性筛选 + 价值化总结

读 `/tmp/ai-infra-*.json`，对每个 source：

- **GitHub PR**：都是 infra 仓，按 `labels`/标题归类（MoE/EP · KV Cache · 调度/Serving · Attention · Speculative · 量化/Kernel · 通信重叠 · 硬件适配(NPU/XPU/ROCm) · Omni(TTS/Diffusion/Pipeline)）。每条**一句话讲推理/工程价值（不要照抄标题）**，格式：
  `● [标题](url) — 价值。@作者 【Merged｜Open】`
  **Merged 优先排前**（已落地 > 提案）。
- **Release**：若 `github_releases` 非空，单列「🚀 版本发布」，从 release notes 提炼推理相关亮点 + 链接。
- **论文**：从 `papers_hf`（高票优先）+ `papers_arxiv` 里挑**与推理/部署强相关**的（量化/KV cache/MoE/attention/调度/kernel/长上下文…），丢弃训练/RL/纯算法噪声。每条一句**推理视角**价值 + 链接（HF `papers/<id>` 或 arXiv abs）。≤8 条。
- **HF 模型发布**（`hf_models`）：deepseek 等组织今天新上的模型/权重（如 DSpark 投机解码 checkpoint）。每条带 likes + HF 链接，一句话说它是什么、对推理的意义。
- **HN + Reddit**：只留推理/量化/部署/本地化强相关的，带 `分数⬆/评论数💬` + 链接。无则写「（今日无相关讨论）」。
- **博客**：挑推理栈相关的，带链接 + 日期。

### Step 4：排序与结构（**质量关键**）

严格按此结构写报告，**每条都必须带可点击链接**（markdown `[文字](url)`）：

```markdown
📋 AI 推理优化日报 — YYYY-MM-DD

📌 今日速览
用 2-3 句话**先讲结论**：今天 AI 推理栈最值得关注的 1-3 个动向是什么、为什么重要。这是自动提炼的「重点摘要」，放在最前面，让人 30 秒抓住要点。

⚡ 今日 TL;DR
1) 一句话最高信号（**跨源联动优先**）— [链接]
…（≤5 条，是今天唯一必读的部分）

🔧 GitHub PR 动态
SGLang / vLLM / vLLM-Omni / SGLang-Omni —— 各仓按类目，Merged 优先；
每仓只详列高信号的 8-12 条，**剩余折叠成一个 bullet**（务必以 `● ` 开头才能在邮件里渲染链接）：
`● 其他 N 条：[#123](url) · [#456](url) · …`

🚀 版本发布            ← 有 release 才出现

🤗 模型 / 权重发布      ← 有 hf_models 才出现（如 DeepSeek DSpark；带 likes + HF 链接）

📄 值得关注的论文       ← ≤8 条，推理视角

📰 博客与新闻

💬 社区讨论（HN + r/LocalLLaMA）

⭐ 跨源联动洞察          ← ≤4 条，PR×论文 / PR×release / 框架对比 等
```

### Step 5：写报告

把报告写到给定的报告路径（默认 `ai-infra-agent/reports/YYYY-MM-DD.md`）。

### Step 6：发邮件

```bash
/usr/bin/python3 scripts/send_mail.py <报告路径>
```

成功末行 `MAIL SENT`，失败 `MAIL FAILED: <原因>`。

### Step 7：汇报

输出：报告路径、各源 kept 计数（含 dedup dropped）、邮件结果。

---

## range 模式差异（回顾报告）

抓取改为：`python3 scripts/fetch_sources.py --mode range --since <X> > /tmp/range.json`
（range 模式**跳过 dedup_state**，要全量；HF Daily / Reddit 在 range 下为空，正常）。

报告**不平铺 PR**，而是趋势化：

```markdown
📈 AI 推理趋势回顾 — <since> → <today>

📌 本期综述
2-3 句话总括：这段时间 AI 推理栈最大的 1-2 条主线 / 拐点是什么。先结论，放最前面。

⚡ 本期大趋势 TL;DR（≤6 条主题，每条一句话 + 代表性链接）

🚀 版本演进          ← 以 github_releases 为骨架，每个版本提炼推理亮点
<按主题展开，每个主题 3-5 条代表性 merged PR / release / 论文，都带链接>
  · 主题1（如 PD 分离 / 大规模 EP）
  · 主题2（如 KV cache / 量化）
  …

📄 本期高信号论文

📰 本期重要博客
```

以「半年/一年内发生了什么、趋势是什么」为目标，代表性条目即可，不求全列。

---

## 注意事项

- **抓取与去重已脚本化**：不要再手动 WebFetch GitHub PR 列表页或 arXiv recent 页。脚本失败时看 stderr，单源为空是正常的。
- **链接是邮件可用性的命脉**：每个条目都要带 `[标题](url)`，不要只写 `PR #123`。
- 某源为空就跳过该节，**不要硬凑**。
- 报告里**不要**出现图片 markdown。
- 不访问内网，仅公开源。
