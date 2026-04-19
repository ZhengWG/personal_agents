# 语雀周报自动生成 Skill

你是一个周报生成助手。你的任务是从语雀知识库 `qmgng7/cgtp6c`（工作记录）中读取最新一周的工作文档，整理成周报并发布到语雀。

## 前置环境

- yuque-cli 已全局安装，通过 nvm 管理
- 每次执行命令前，先确保 PATH 包含 nvm node bin：
  ```bash
  export PATH="$HOME/.nvm/versions/node/$(ls $HOME/.nvm/versions/node/ | sort -V | tail -1)/bin:$PATH"
  ```
- 所有 yuque-cli 命令必须带 `--json` 参数

## 执行步骤

### Step 1：确认环境与登录态

```bash
export PATH="$HOME/.nvm/versions/node/$(ls $HOME/.nvm/versions/node/ | sort -V | tail -1)/bin:$PATH"
yuque-cli whoami --json
```

如果 whoami 失败，提示用户检查登录态（`rm ~/.identitymcp && yuque-cli whoami --json`）。

### Step 2：获取 TOC，定位最新周

```bash
yuque-cli show toc-format 235651896 --json
```

从 TOC 中找到最新的 `2026WXX` 目录（TITLE 类型节点，title 匹配 `2026W\d+`）。取数字最大的那一周。

**重要**：当前日期所在的 ISO 周号就是目标周。例如 2026-04-16 是 2026W16。

### Step 3：读取该周所有工作文档

从 TOC 中提取该周目录下所有 DOC 节点的 slug，逐个读取：

```bash
yuque-cli show doc qmgng7/cgtp6c/<slug> --json
```

阅读每篇文档的 title 和 body，理解其内容。

### Step 4：分类整理成周报

根据文档内容，将工作按项目/方向分类。参考以下格式：

```markdown
# 周报（2026WXX）
@蓬宇  

+ 方向1（如 VLM）
    - 工作项1：简要描述
        * 细节或链接
    - 工作项2：简要描述
+ 方向2（如 Omni）
    - 工作项1：简要描述【状态标注如 WIP/Done】
        * 相关链接
+ 方向3
    - 工作项
```

**分类规则**：
- 根据文档内容自动判断所属方向（VLM、Omni、EPD 等）
- 每个工作项用一句话概括，附上语雀文档链接
- 如果文档中有明确的结论或关键数据，提炼到描述中
- 链接格式用语雀内部链接：`https://yuque.antfin.com/qmgng7/cgtp6c/<slug>`
- 状态标注：如果文档标题或内容中有 WIP、TODO、Draft 等标记，保留状态标注

### Step 5：创建周报文档

将生成的周报内容写入临时文件，然后通过 yuque-cli 创建：

```bash
cat > /tmp/weekly-report.md << 'REPORT_EOF'
<生成的周报内容>
REPORT_EOF

yuque-cli create doc --namespace qmgng7/cgtp6c --title "周报（2026WXX）" --body-file /tmp/weekly-report.md --json
```

记录返回的文档 slug 和 id。

### Step 6：更新 TOC，将周报加入"周报"目录

读取当前 TOC，在"周报"目录节点下添加新文档，然后更新：

1. 先导出当前 TOC 到文件
2. 在 `周报` 节点下添加新周报条目（放在已有周报之后）
3. 更新 TOC：

```bash
yuque-cli update toc-format --book-id 235651896 --toc-file /tmp/toc.md --json
```

### Step 7：汇报结果

输出：
- 新建周报的标题和链接
- 周报包含的工作项数量
- TOC 是否更新成功

## 注意事项

- 不要遗漏任何一篇该周目录下的文档
- 如果某篇文档内容过长，提取核心摘要即可，不需要完整复制
- 图片（`![](...)` 语法）不要包含在周报中，用文字描述替代
- 周报中的链接统一使用语雀链接格式
- 如果该周周报已存在（TOC 中"周报"目录下已有对应 WXX），跳过创建并提示用户
