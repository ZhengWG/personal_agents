# personal_agents

用于托管可自动化、可周期执行的个人 Agents（例如通过 GitHub Actions 定时运行）。

## 已提供的第一个 Agent

### weekly_repo_brief

功能：每周自动读取仓库最近 7 天提交信息，并调用大模型生成中文周报（Markdown）。

- 入口脚本：`agents/weekly_repo_brief.py`
- 工作流：`.github/workflows/weekly-repo-brief.yml`
- 默认触发：
  - `schedule`: 每周一 UTC 01:00
  - `workflow_dispatch`: 支持手动触发

## 模型能力说明（可以用到“类似 Codex 的能力”）

可以。这个 Agent 本质上是调用模型 API 来完成总结和建议输出，能力上与“代码理解/生成类模型”一致，差异主要在你配置的模型名与服务端点。

当前支持通过环境变量配置：

- `OPENAI_API_KEY`（必填，正式调用）
- `OPENAI_API_BASE`（可选，默认 `https://api.openai.com/v1`）
- `AGENT_MODEL`（可选，默认 `gpt-4.1-mini`）

> 如果你的平台提供了 Codex/兼容模型，只需要把 `AGENT_MODEL`（必要时加 `OPENAI_API_BASE`）改为对应值即可。

## GitHub 配置步骤

1. 在仓库 `Settings -> Secrets and variables -> Actions` 中添加：
   - Secret: `OPENAI_API_KEY`
2. （可选）添加 Variables：
   - `AGENT_MODEL`（例如你的 Codex/兼容模型名）
   - `OPENAI_API_BASE`（如果不是官方 OpenAI 地址）
3. 进入 `Actions`，运行 `Weekly Repo Brief Agent` 验证结果。

## 本地调试

```bash
python agents/weekly_repo_brief.py --dry-run
```

正式调用（需要 API Key）：

```bash
OPENAI_API_KEY=your_key python agents/weekly_repo_brief.py
```
