# Personal Agents

个人自动化 agent 集合。

## Skills

- `/weekly-report` — 从语雀知识库自动生成周报。读取最新一周的工作文档，分类整理后发布到语雀周报目录。
- `/daily-ai-infra` — 每天 09:00 抓取 AI infra 推理动态（SGLang/vLLM/vLLM-Omni/SGLang-Omni + arXiv + 博客 + Reddit），生成日报并邮件发送。凭证读 `~/.config/ai-infra-agent/mail.env`。

## 环境说明

- Node.js 通过 nvm 管理，lazy init 模式。非交互 shell 中需要手动加载 nvm bin 到 PATH。
- yuque-cli (`@antcli/yuque-ant-cli`) 已全局安装，走 `~/.identitymcp` 认证，不需要 YUQUE_TOKEN。
- 语雀知识库 namespace: `qmgng7/cgtp6c`，book_id: `235651896`
