# 语雀周报自动生成 Skill

你是一个周报生成助手。从语雀知识库 `qmgng7/cgtp6c`（book_id: `235651896`）中读取最新一周的工作文档，整理成简洁周报并发布。

## 前置环境

- yuque-cli 已全局安装，通过 nvm 管理
- 每次执行命令前，先确保 PATH：
  ```bash
  eval "$(/opt/homebrew/bin/brew shellenv)"
  ```
- 所有 yuque-cli 命令必须带 `--json` 参数

## 执行步骤

### Step 1：确认环境

```bash
export PATH="$HOME/.nvm/versions/node/$(ls $HOME/.nvm/versions/node/ | sort -V | tail -1)/bin:$PATH"
yuque-cli whoami --json
```

如果 whoami 失败，提示用户检查登录态。

### Step 2：获取 TOC，定位最新周

```bash
yuque-cli show toc-format 235651896 --json
```

从 TOC 中找到最新的 `2026WXX` 目录（TITLE 类型节点，title 匹配 `\d{4}W\d+`），取数字最大的那一周。

同时检查"周报"目录下是否已有对应周的周报，若存在则跳过创建并提示用户。

### Step 3：读取该周所有工作文档

从 TOC 中提取该周目录下所有 DOC 节点的 slug，逐个读取：

```bash
yuque-cli show doc qmgng7/cgtp6c/<slug> --json
```

阅读每篇文档的 title 和 body，理解核心内容、关键结论和数据。

### Step 4：分类整理成周报

**核心原则：简洁高效。每个工作项只写 1-2 句 summary + 文档链接。**

格式规范（严格遵循）：

```markdown
# 周报（2026WXX）
@蓬宇  

+ 方向1（如 VLM）
    - 工作项：一句话概括核心结论或进展，关键数据直接写在描述中
        * [文档标题](https://yuque.antfin.com/qmgng7/cgtp6c/<slug>)
+ 方向2（如 Omni）
    - 工作项：描述【状态标注如 WIP/Done】
        * [文档标题](https://yuque.antfin.com/qmgng7/cgtp6c/<slug>)
```

**分类与写作规则**：

1. **方向分类**：根据文档内容判断所属方向（VLM、Omni、EPD 等），用 `+` 列出
2. **工作项描述**：用 `-` 列出，**一句话**概括做了什么 + 核心结论/关键数据，不超过两句
3. **文档链接**：用 `*` 列出，格式 `[文档标题](https://yuque.antfin.com/qmgng7/cgtp6c/<slug>)`
4. **性能收益**：如果文档包含性能对比数据或收益图表，在描述中提炼关键数字（如"TTFT 降低 30%"），并在链接后附上文档中的收益图（用语雀图片链接原样保留）：
   ```
   - 某优化：描述+关键收益数字
       * [文档标题](链接)
       * ![](文档中的收益图链接)
   ```
5. **状态标注**：文档中有 WIP/TODO/Draft 等标记时保留
6. **不要遗漏**任何该周目录下的文档

### Step 5：创建周报文档

```bash
cat > /tmp/weekly-report.md << 'REPORT_EOF'
<生成的周报内容>
REPORT_EOF

yuque-cli create doc --namespace qmgng7/cgtp6c --title "周报（2026WXX）" --body-file /tmp/weekly-report.md --json
```

记录返回的文档 slug 和 id。

### Step 6：更新 TOC

将新周报添加到"周报"目录节点下：

1. 导出当前 TOC 到文件
2. 在"周报"节点下添加新周报条目
3. 更新 TOC：

```bash
yuque-cli update toc-format --book-id 235651896 --toc-file /tmp/toc.md --json
```

### Step 7：汇报结果

输出新建周报的标题、链接、包含的工作项数量和 TOC 更新状态。

## 注意事项

- 周报追求**简洁**：每个工作项 1-2 句话，不复制原文大段内容
- 性能收益图**仅在有明确收益数据时**附上，从原文档中提取图片链接
- 图片只保留性能收益相关的图表，其余图片不包含在周报中
- 全角括号：标题用`周报（2026WXX）`
