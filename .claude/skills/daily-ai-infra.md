# AI 推理优化日报生成 Skill

你是一个 AI 推理基础设施情报助手。任务：每天从 7 个公开源抓取过去 24-48 小时的 AI infra 推理相关动态，整理成日报，保存到文件并发送邮件。

## 前置环境

- Node.js 通过 nvm 管理，需先加载 PATH：
  ```bash
  export PATH="$HOME/.nvm/versions/node/$(ls $HOME/.nvm/versions/node/ | sort -V | tail -1)/bin:$PATH"
  ```
- Python3 系统自带（`/usr/bin/python3`），用于解析 JSON 与发邮件
- 报告输出目录：`~/Projects/personal_agents/ai-infra-agent/reports/YYYY-MM-DD.md`
- 邮件发送脚本：`~/Projects/personal_agents/scripts/send_mail.py`
- 邮件凭证：`~/.config/ai-infra-agent/mail.env`（SMTP_USER / SMTP_PASS / MAIL_TO）

## 信息源（4 类 7 个源）

| 类别 | 源 | 抓取方式 |
|---|---|---|
| GitHub PR | `sgl-project/sglang` | WebFetch GitHub PR 搜索页 |
| GitHub PR | `vllm-project/vllm` | WebFetch |
| GitHub PR | `vllm-project/vllm-omni` | WebFetch |
| GitHub PR | `sgl-project/sglang-omni` | WebFetch |
| 论文 | arXiv cs.LG recent + HuggingFace Papers | WebFetch |
| 博客 | HuggingFace Blog、Interconnects AI、The Neuron | WebFetch |
| 社区 | Reddit r/LocalLLaMA top/day | `curl` JSON（WebFetch 被墙） |

## 执行步骤

### Step 1：环境 + 日期

```bash
export PATH="$HOME/.nvm/versions/node/$(ls $HOME/.nvm/versions/node/ | sort -V | tail -1)/bin:$PATH"
TODAY=$(date +%Y-%m-%d)
YESTERDAY=$(date -v-1d +%Y-%m-%d)
REPORT=/Users/guanxiangtian/Projects/personal_agents/ai-infra-agent/reports/${TODAY}.md
```

### Step 2：并行抓取 4 个 GitHub PR 源

对每个仓库，WebFetch 以下 URL，提取"updated >= 昨天"的 PR（PR 号 / 标题 / 状态 / 作者）：

- `https://github.com/sgl-project/sglang/pulls?q=is%3Apr+updated%3A%3E%3D<YESTERDAY>+sort%3Aupdated-desc`
- `https://github.com/vllm-project/vllm/pulls?q=is%3Apr+updated%3A%3E%3D<YESTERDAY>+sort%3Aupdated-desc`
- `https://github.com/vllm-project/vllm-omni/pulls?q=is%3Apr+updated%3A%3E%3D<YESTERDAY>+sort%3Aupdated-desc`
- `https://github.com/sgl-project/sglang-omni/pulls?q=is%3Apr+updated%3A%3E%3D<YESTERDAY>+sort%3Aupdated-desc`

每仓 up to 30 条。

### Step 3：抓论文

- `https://arxiv.org/list/cs.LG/recent` — 筛选：quantization / MoE / KV cache / attention / speculative decoding / inference / kernel
- `https://huggingface.co/papers` — 取 top trending 里与推理优化相关的

提取：arXiv ID、标题、一句话摘要。

### Step 4：抓博客

- `https://huggingface.co/blog` — 最近 7 天
- `https://www.interconnects.ai/archive?sort=new` — 最近 7 天
- `https://www.theneurondaily.com/` — 最近 3 天

### Step 5：抓 Reddit（必须用 curl，WebFetch 被屏蔽）

```bash
curl -s -A "daily-ai-infra-agent/0.1" "https://www.reddit.com/r/LocalLLaMA/top.json?t=day&limit=20" \
  | /usr/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
for p in d['data']['children']:
    x = p['data']
    print(f\"[{x['score']}⬆ {x['num_comments']}💬] [{x.get('link_flair_text') or ''}] {x['title']}\")
    body = (x.get('selftext') or '')[:300].replace('\n',' ')
    if body.strip(): print(f'  > {body}')
    print(f\"  https://www.reddit.com{x['permalink']}\\n\")
"
```

### Step 6：分类整理成日报

严格按照以下模板输出到 `$REPORT`：

```markdown
📋 AI 推理优化日报 — YYYY-MM-DD

🔧 GitHub PR 动态

SGLang (sgl-project/sglang)
[分类展开：MoE / KV Cache / 调度 / Attention / Speculative / 量化 / 其他]
● PR #NUM [状态] 标题 — 一句话说推理/工程价值。@作者

vLLM (vllm-project/vllm)
[同样分类]

vLLM-Omni (vllm-project/vllm-omni)
[分类：Omni/TTS / Diffusion / MoT Kernel / Offload / 硬件适配]

SGLang-Omni (sgl-project/sglang-omni)
[分类：多阶段 pipeline / MoE+并行 / Benchmark]

📄 值得关注的论文
● arXiv:YYMM.NNNNN — 标题
  一句话推理优化视角的价值。

📰 博客与新闻
● 来源: 标题 (日期) — 摘要与推理栈关联。

💬 社区讨论（r/LocalLLaMA Top of Day）
● "标题" (⬆数 💬数) — 推理/量化角度的要点。
  https://reddit.com 链接

⭐ 今日重点推荐
1) 跨源交叉的抓手 1（比如某 PR + 某论文联动）
2) 跨源交叉的抓手 2
3) 跨源交叉的抓手 3
4) Omni 专线的抓手（必须有一条关注 vllm-omni + sglang-omni 的联动）
```

**分类与质量准则**：

- PR 每条一句话**讲推理/工程价值**，不要照抄标题；作者 `@username` 保留
- 论文摘要必须**从推理/部署视角**总结，不是学术摘要
- Reddit 只保留与推理 / 量化 / 部署 / 本地化强相关的
- 重点推荐做**跨源联动**（PR × 论文，或 PR × 社区讨论），不是简单罗列
- 如果某日某源完全没东西，写 "（今日无值得关注更新）"，不要硬凑
- 绝对不要在报告里带图片 markdown 语法

### Step 7：发邮件

```bash
/usr/bin/python3 /Users/guanxiangtian/Projects/personal_agents/scripts/send_mail.py "$REPORT"
```

脚本自己读 `~/.config/ai-infra-agent/mail.env`，失败时 exit 非 0 让 cron 日志捕获。

### Step 8：汇报

输出：
- 报告路径
- PR / 论文 / 博客 / Reddit 各分类条数
- 邮件发送是否成功（stdout 末行："MAIL SENT" / "MAIL FAILED: <原因>"）

## 注意事项

- **不要发送空报告**：如果 4 个 GitHub 源全部 0 条，退化为只发论文+博客+Reddit；如果全部 0 条，跳过发邮件并输出 "NO CONTENT"
- **错误处理**：某个源失败（404 / 超时），跳过该源但继续其他源
- **链接格式**：Reddit 链接用完整 `https://www.reddit.com/r/LocalLLaMA/...`；arXiv 用 `arXiv:YYMM.NNNNN` 字符串，让邮件客户端自动识别
- **不要访问内网**：语雀等内网地址不在本 skill 范围，仅公开源
- **颗粒度**：每仓 PR 保留 15-25 条最相关的即可，不要全列
