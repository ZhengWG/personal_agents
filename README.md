# personal_agents

用于托管可自动化、可周期执行的个人 Agents（例如通过 GitHub Actions 定时运行）。

## 已提供的 Agents

### weekly_repo_brief

功能：每周自动读取仓库最近 7 天提交信息，并调用大模型生成中文周报（Markdown）。

- 入口脚本：`agents/weekly_repo_brief.py`
- 工作流：`.github/workflows/weekly-repo-brief.yml`
- 默认触发：
  - `schedule`: 每周一 UTC 01:00
  - `workflow_dispatch`: 支持手动触发

### daily_ai_inference_digest

功能：每天自动抓取 AI 推理优化相关动态（GitHub PR / arXiv / 新闻 RSS / Reddit），生成中文《AI 推理优化日报》。

- 入口脚本：`agents/daily_ai_inference_digest.py`
- 工作流：`.github/workflows/daily-ai-inference-digest.yml`
- 默认触发：
  - `schedule`: 每天 UTC 01:30
  - `workflow_dispatch`: 支持手动触发
- 输出内容：
  - Markdown 日报：`agent_outputs/ai-inference-digest-*.md`
  - 原始数据快照：`agent_outputs/ai-inference-digest-*.json`

日报固定结构（与你给的模板一致）：
- `[YYYY-MM-DD] AI 推理优化日报`
- `📋 AI 推理优化日报 — YYYY-MM-DD`
- `🔧 GitHub PR 动态`
- `📄 值得关注的论文`
- `📰 博客与新闻`
- `💬 社区讨论`
- `⭐ 今日重点推荐`

## 模型能力说明（可以用到“类似 Codex 的能力”）

可以。这个 Agent 本质上是调用模型 API 来完成总结和建议输出，能力上与“代码理解/生成类模型”一致，差异主要在你配置的模型名与服务端点。

当前支持通过环境变量配置：

- `OPENAI_API_KEY`（必填，正式调用）
- `OPENAI_API_BASE`（可选，默认 `https://api.openai.com/v1`）
- `AGENT_MODEL`（可选，默认 `gpt-4.1-mini`）

> 如果你的平台提供了 Codex/兼容模型，只需要把 `AGENT_MODEL`（必要时加 `OPENAI_API_BASE`）改为对应值即可。

`daily_ai_inference_digest` 额外支持以下可选变量：

- `TRACKED_GITHUB_REPOS`（默认 `sgl-project/sglang,vllm-project/vllm`）
- `TRACKED_NEWS_FEEDS`（格式 `名称|RSS_URL,名称|RSS_URL`）
- `TRACKED_SUBREDDITS`（默认 `LocalLLaMA`）
- `ARXIV_QUERY`（arXiv 检索表达式）
- `GITHUB_LOOKBACK_HOURS`（默认 `48`）
- `GITHUB_PR_LIMIT`、`ARXIV_LIMIT`、`NEWS_FEED_LIMIT`、`REDDIT_LIMIT`

## GitHub 配置步骤

1. 在仓库 `Settings -> Secrets and variables -> Actions` 中添加：
   - Secret: `OPENAI_API_KEY`
2. （可选）添加 Variables：
   - `AGENT_MODEL`（例如你的 Codex/兼容模型名）
   - `OPENAI_API_BASE`（如果不是官方 OpenAI 地址）
   - （日报 agent 可选）上面的 `TRACKED_*`、`ARXIV_QUERY`、`*_LIMIT` 变量
3. 进入 `Actions`，运行对应工作流验证结果：
   - `Weekly Repo Brief Agent`
   - `Daily AI Inference Digest`

## 本地调试

```bash
python agents/weekly_repo_brief.py --dry-run
```

正式调用（需要 API Key）：

```bash
OPENAI_API_KEY=your_key python agents/weekly_repo_brief.py
```

AI 推理优化日报本地调试：

```bash
# 使用内置 mock 数据验证版式
python agents/daily_ai_inference_digest.py --dry-run

# 抓取真实数据但不调用模型（纯规则渲染）
python agents/daily_ai_inference_digest.py --no-llm

# 抓取真实数据并调用模型总结
OPENAI_API_KEY=your_key python agents/daily_ai_inference_digest.py
```
