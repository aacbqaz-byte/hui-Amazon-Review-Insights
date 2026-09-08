# Amazon Review Insights Skill

一个可移植的 Agent Skill：通过已配置的 SellerSprite MCP 采集 Amazon ASIN 评论，完整保存最多 2,000 条记录，并生成带证据链的独立 HTML 洞察报告。

它不绑定 Codex、Claude 或某一家智能体。任何支持 `SKILL.md`、MCP 工具调用和本地文件写入的智能体都可以导入此 Skill。

## 能力

- 调用 `sellersprite-mcp` 的 `review` 能力，按每页 20 条自动翻页采集评论。
- 强制要求 `asin` 和 `marketplace`；缺少站点时先询问，不猜测默认站点。
- 最多采集 2,000 条；不足 2,000 条时采集接口可返回的全部评论，不做比例抽样。
- 每页 MCP 结果立即完整写入本地事务式缓存；上下文压缩或任务中断后只从下一未保存页继续。
- 完成、部分失败或已有已验证 HTML 时禁止自动重复调用 MCP。
- 支持内置提示词或用户上传的 `.md` / `.txt` 分析提示词；自定义提示词只能改变分析视角。
- 输出无外部依赖的离线 HTML；其中嵌入全部评论，支持导航、中英文切换、模糊搜索、星级筛选和每页 20 条用户原声。
- 用户提供真实产品事实后，可额外生成 Listing、A+ 内容计划与设计 Brief。

## 前置条件

1. 智能体宿主支持加载 `SKILL.md` 格式的 Skill。
2. 宿主已连接 SellerSprite MCP，并向智能体公开名为 `review` 的评论查询能力。
3. 该能力需要这些参数：

   ```text
   必填：marketplace、asin
   可选：starList、typeList、page、size
   ```

4. 智能体可在本地工作区写入文件，并可运行 Python 3 标准库脚本。

本 Skill 不保存密钥，不自行安装 MCP，也不直接请求 SellerSprite HTTP API。

## 安装

将整个 `amazon-review-insights` 文件夹导入或复制到你的智能体宿主的 Skills 目录，再按照该宿主的方式启用它。

```text
amazon-review-insights/
├── SKILL.md
├── references/
│   └── built-in-analysis-prompt.md
└── scripts/
    └── review_cache.py
```

若宿主的 MCP 工具名称与 `review` 不同，请将它映射为同等的 SellerSprite 评论查询能力；参数和返回字段必须与 Skill 的要求兼容。

## 使用示例

```text
帮我采集并分析 ASIN B0XXXXXXX 在 US 站的评论。
```

```text
抓取 B0XXXXXXX 的一星和二星评论，市场为 DE，使用我上传的提示词分析。
```

采集结束后，Skill 会询问是否分析，并提供内置提示词或自定义提示词选择。最终报告会保存为类似下面的文件：

```text
amazon-review-report-B0XXXXXXX-US-20260907-120000.html
```

## 重要边界

- SellerSprite 接口未提供文档化的 Amazon 全站评论总数；报告会显示“SellerSprite 返回评论数”，不会把它称为 Amazon 全量评论。
- 使用星级或类型筛选时，报告会醒目标记为“筛选样本，不代表所有买家”。
- 评论洞察、意图聚类与优先级是模型基于样本的推断，应结合访谈、问卷或其他研究验证。
- Listing、A+ 与设计 Brief 仅使用用户提供的产品事实；Skill 不承诺平台合规、搜索排名、Rufus 推荐或销售结果。

## 验证

缓存脚本只使用 Python 标准库，不需要额外依赖。Skill 格式校验器需要 `PyYAML`，可运行：

```powershell
python -m pip install PyYAML
$env:PYTHONUTF8 = '1'
python 'C:\Users\jjh09\.codex\skills\.system\skill-creator\scripts\quick_validate.py' '.\amazon-review-insights'
python -m unittest discover -s tests -v
```

预期输出：`Skill is valid!`

## 仓库内容

- `amazon-review-insights/`：可导入的 Skill 源码。
- `docs/superpowers/specs/`：已确认的设计规格。
- `docs/superpowers/plans/`：实施计划。
