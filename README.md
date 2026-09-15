# Amazon Review Insights Skill

一个可移植的 Agent Skill：通过已配置的 SellerSprite MCP 采集 1–5 个 Amazon ASIN 的评论，默认每个 ASIN 最多 2,000 条，生成带证据链的独立 HTML 洞察报告。2–5 个 ASIN 会在同一报告中分析共性需求、共性缺口与各 ASIN 差异。

它不绑定 Codex、Claude 或某一家智能体。任何支持 `SKILL.md`、MCP 工具调用和本地文件写入的智能体都可以导入此 Skill。

## 能力

- 调用 `sellersprite-mcp` 的 `review` 能力，新采集任务按每页 50 条自动翻页采集评论。
- 强制要求 1–5 个唯一 ASIN 和明确的 `marketplace`；一个批次使用同一站点、筛选条件和每个 ASIN 的采集上限。
- 默认每个 ASIN 最多采集 2,000 条；可用 `--limit` 指定 50–2,000 之间的 50 的整数倍。不足上限时采集接口可返回的全部评论，不做比例抽样。
- 每页 MCP 结果立即完整写入本地事务式缓存；上下文压缩或任务中断后只从下一未保存页继续。
- 完成、部分失败或已有已验证 HTML 时禁止自动重复调用 MCP。
- 已存在的每页 20 条旧缓存或 HTML 回执会继续复用；不会为了升级到 50 条而重新采集。
- 支持内置提示词或用户上传的 `.md` / `.txt` 分析提示词；自定义提示词只能改变分析视角。
- 输出无外部依赖的离线 HTML；嵌入全部评论，支持导航、中英文切换，以及 ASIN、模糊搜索、多选星级、已验证购买状态的组合筛选，每页显示 20 条用户原声。
- 联合报告包含十个视图：总览、共性意图、共性缺口、ASIN 差异、机会矩阵、Listing 与 A+、设计 Brief、用户原声、数据与方法、限制说明。单 ASIN 保留八视图与原有工作流。
- 共性结论至少覆盖 `ceil(0.6 × ASIN 数)` 个成员，按各 ASIN 内归一化频率的算术平均排序，同时显示原始条数、独立证据数与覆盖率，避免大样本 ASIN 主导结论。
- 跨 ASIN 重复评论在用户原声中完整保留；共性证据只计一次，不能用复制评论制造多个 ASIN 的独立支持。
- 用户提供一个独立的新建/待优化产品的真实事实后，可生成可直接改用的 Listing、A+ 文案与包含“做什么、为什么、给谁、验收标准”的设计 Brief。

## 前置条件

1. 智能体宿主支持加载 `SKILL.md` 格式的 Skill。
2. 宿主已连接 SellerSprite MCP，并向智能体公开名为 `review` 的评论查询能力。
3. 该能力需要这些参数：

   ```text
   必填：marketplace、asin
   可选：starList、typeList、page、size
   ```

4. 智能体可在本地工作区写入文件，并可运行 Python 3 标准库脚本。
5. 本地安装 Node.js，用于在交付及清理缓存前执行离线 HTML 内联 JavaScript 语法校验。

本 Skill 不保存密钥，不自行安装 MCP，也不直接请求 SellerSprite HTTP API。

## 安装

将整个 `amazon-review-insights` 文件夹导入或复制到你的智能体宿主的 Skills 目录，再按照该宿主的方式启用它。

```text
amazon-review-insights/
├── SKILL.md
├── references/
│   └── built-in-analysis-prompt.md
└── scripts/
    ├── review_cache.py
    ├── batch_review_cache.py
    └── validate_report.py
```

若宿主的 MCP 工具名称与 `review` 不同，请将它映射为同等的 SellerSprite 评论查询能力；参数和返回字段必须与 Skill 的要求兼容。

## 使用示例

```text
帮我采集并分析 ASIN B0XXXXXXX 在 US 站的评论。
```

```text
抓取 B0XXXXXXX 的一星和二星评论，市场为 DE，使用我上传的提示词分析。
```

```text
分析 US 站 B000000001、B000000002、B000000003 的评论，每个最多 500 条，不筛选。
用内置提示词，重点比较通勤场景的共性缺口与各产品差异。
```

采集结束后，Skill 会确认尚未确定的分析与提示词选择；已明确的选择不会重复询问。最终报告会保存为类似下面的文件：

```text
amazon-review-report-B0XXXXXXX-US-20260907-120000.html
amazon-review-report-batch-<id>-US-20260915-120000.html
```

## 批次执行与中断恢复

单 ASIN 继续使用 `review_cache.py`；2–5 个 ASIN 使用 `batch_review_cache.py`。以下占位符需替换为实际值；有空格的路径需加引号。

```text
python <skill-dir>/scripts/batch_review_cache.py init --workspace <workspace> --marketplace US --asins B000000001 B000000002 --limit 500
python <skill-dir>/scripts/batch_review_cache.py status --workspace <workspace> --batch-id <返回的batchId>
python <skill-dir>/scripts/batch_review_cache.py next-request --workspace <workspace> --batch-id <batchId> --asin B000000001
```

只在 `action: "call_mcp"` 时将返回的 `request` 原样传给 MCP。每次响应立即完整保存为临时 JSON，再运行对应成员的 `save-page --response-file <file>`（成功）或 `record-error --response-file <file>`（非 OK）；这些命令同样必须带 `--workspace`、`--batch-id`、`--asin`。新采集一律每页 50 条；只有匹配的既存 size-20 状态可以继续用 20，不能为升级页大小重爬。

批次清单位于 `.amazon-review-insights-cache/batches/<batch-id>/manifest.json`；成员评论与分页状态位于 `collections/<identity>/`。上下文压缩或中断后先读取清单并运行 `status`，再由每个成员的 `next-request` 授权。`REQUEST_PENDING` 只能提交已获得的响应，响应丢失则停止，禁止重复请求该页。默认顺序执行；宿主支持并行时，每个 ASIN 必须只有一个写入者，导出/验证须等所有写入者结束。默认上限下，2–5 个全新 ASIN 最多需要 80–200 次分页调用；实际时间取决于返回页数、接口延迟和本地分析，已有缓存可减少调用。

成员部分失败时保留精确错误码/消息及已采集、去重后条数，由用户决定是否基于部分数据输出。`collecting` 或 `blocked-empty` 成员会阻止整个批次导出，CLI 没有“跳过成员”参数；若用户选择缩小比较范围，再用选定成员建立新批次并明确披露原始失败和范围变更。`partial` 不能自动重试；只有用户明确要求刷新，才调用单成员 `review_cache.py init --refresh`（批次 init 没有 refresh 参数）。

```text
python <skill-dir>/scripts/batch_review_cache.py export-json --workspace <workspace> --batch-id <batchId> --output <input.json>
python <skill-dir>/scripts/validate_report.py <report.html>
python <skill-dir>/scripts/batch_review_cache.py finalize-html --workspace <workspace> --batch-id <batchId> --html <report.html>
```

导出包含批次 `metadata`、各成员 `datasets`、原样展平的 `reviews` 和等长 `sourceIndex`。联合 HTML 分别嵌入 `review-data` 与 `review-source-index`，保留每条评论全部原始字段；界面按索引关联 ASIN。必须由批次 finalizer 验证每个成员的数据条数与 SHA-256 后写入全部回执，再清理成员实时缓存。验证失败或只导出 Excel 时保留缓存。后续单 ASIN/批次输出都从回执指向的已验证 HTML 恢复，文件丢失或被修改时停止，不自动重爬。联合 HTML 不能用单 ASIN finalizer 清理。

## 重要边界

- SellerSprite 接口未提供文档化的 Amazon 全站评论总数；报告会显示“SellerSprite 返回评论数”，不会把它称为 Amazon 全量评论。
- 使用星级或类型筛选时，报告会醒目标记为“筛选样本，不代表所有买家”。
- 评论洞察、意图聚类与优先级是模型基于样本的推断，应结合访谈、问卷或其他研究验证。
- Listing、A+ 与设计 Brief 服务于一个独立的新建/待优化目标产品。所比较 ASIN 的评论不能证明目标产品的材质、成分、规格、认证或性能；最低需要目标产品 Top 3 features 与 material / composition / specifications。缺失时显示所需输入，不编造文案。
- Skill 不声称掌握 COSMO/Rufus 内部机制，不承诺平台合规、搜索排名、Rufus 推荐或销售结果。

## 验证

缓存与报告校验脚本只使用 Python 标准库；报告校验还会调用本地 Node.js 的 `node --check`。Skill 格式校验器需要 `PyYAML`，可运行：

```powershell
python -m pip install PyYAML pytest
$env:PYTHONUTF8 = '1'
python 'C:\Users\jjh09\.codex\skills\.system\skill-creator\scripts\quick_validate.py' '.\amazon-review-insights'
python '.\amazon-review-insights\scripts\validate_report.py' '<生成的 HTML 路径>'
python -m pytest -q
```

预期输出：`Skill is valid!`

## 仓库内容

- `amazon-review-insights/`：可导入的 Skill 源码。
- `docs/superpowers/specs/`：已确认的设计规格。
- `docs/superpowers/plans/`：实施计划。
