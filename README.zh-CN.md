[English](README.md)

# Bookmark Advisor

AI 驱动的 Microsoft Edge 书签整理工具。日常使用 Edge 扩展即可：生成带安全护栏的 AI 整理方案，逐条审核每个操作，通过 `chrome.bookmarks` 执行，并可随时撤销最近一次执行。Python CLI 适用于导出快照 (snapshot)、构建 URL 审核队列、生成富化快照 (enriched snapshot)，以及更深度的离线检查。

## 使用扩展

1. 打开 `edge://extensions`，启用开发者模式，将 `extension/` 目录加载为已解包的扩展。
2. 打开扩展弹窗，切换到 **LLM** 标签，设置：
   - **API base URL**：`https://api.openai.com/v1` 或其他兼容 OpenAI 的 HTTPS 端点
   - **Endpoint mode**：大多数提供商选 `auto` 即可
   - **Model**：默认 `gpt-5.4-mini`；速度快的兼容模型效果最好
   - **API key**：以 AES-GCM 密文形式保存在 `chrome.storage.local`
3. 切回 **Plan** 标签，可选择一个聚焦文件夹 (focus folder)，然后点击 **Generate AI Plan**。
4. 逐条审核操作：批准合理的移动，修改特定行，或将不确定的项目保持待定状态。
5. 点击 **Execute Reviewed Plan**。执行通过 Edge 的 `chrome.bookmarks` API 完成，不会直接编辑书签文件。
6. 如需撤销最新一批执行，点击 **Undo Last Execution**。
7. 点击 **Generate New Plan for Remaining**，继续处理未审核的项目。

扩展无构建步骤、无 SDK 依赖。通过原生 `fetch` 调用兼容 OpenAI 的 REST API，`auto` 模式依次尝试 `chat_json_object → chat_json_schema → chat_plain_json → completions_plain_json → responses_json_schema`。

## 调整偏好设置

弹窗有三个标签，分别控制不同的功能：

**Plan 标签：**
- **Scope（整理范围）** — 将规划和执行限制在单个文件夹树内。留空则规划所有文件夹。
- **Max actions（最多操作数）** — 单次 LLM 请求生成的操作上限（1–80，默认 40）。值越低生成越快；值越高单次覆盖的书签越多。

**LLM 标签：**
- **Endpoint mode（端点模式）** — `auto` 会尝试多种 API 格式并选择可用的。仅在 `auto` 对你的提供商失效时才切换到特定模式。
- **Model（模型）** — 快速模型（`gpt-5.4-mini`、`deepseek-v4-flash`、`gemini-2.5-flash`）效果最好。推理/思考类模型会慢很多。
- **Request timeout（请求超时）** — 每次 LLM 调用的最长等待秒数（10–300，默认 120）。MV3 总上限为 300 秒。
- **Max retries（最大重试次数）** — lint 失败后重试次数（0–3，默认 1）。设为 0 则不重试。

**Preferences（规划偏好）标签：**
- **Language（语言）** — 界面语言：英文或中文（默认英文）。
- **顶层散书签保护** — 开启时（默认），直接挂在根文件夹（`/收藏夹栏`、`/其他收藏夹` 等）下的散落书签不会被移动。如果希望 AI 将它们归类到子文件夹，切换为关闭即可。
- **整理后排序** — 重组后书签的排列方式：保持原顺序（默认）、按标题 A→Z 排序、或 Z→A 排序。
- **规划风格** — AI 的激进程度：`均衡`（默认，合理移动，不确定的保留审查）、`保守`（只移动非常确定的，其余保持原位）、`积极`（尽量全部归类，允许创建新文件夹）。

## 安全设计

| 安全机制 | 行为 |
|----------|------|
| 逐条审核 | 每个操作必须单独批准或满足可执行条件后才会执行 |
| 聚焦范围 | 规划和执行可限制在单个文件夹树内 |
| 策略引擎 (policy engine) | 执行时拦截越界操作 |
| 撤销日志 (undo log) | 记录执行前的 parentId/title，可一键撤销最近一次执行 |
| 隔离区 | 重复书签移至 `_Quarantine` 而非永久删除 |
| 空文件夹清理 | `delete_empty_folder` 执行前再次确认文件夹为空；撤销时重建文件夹路径 |
| 定位校验 (locator checks) | 每次变更前重新读取书签/文件夹 ID |
| 后台任务 | Offscreen 保活心跳、`chrome.alarms` 看门狗、强制取消、启动恢复、执行检查点 |

大文件夹会被拆分为每 50 条书签的提示片段 (prompt part)，并发数为 3，结果合并后去重。普通生成目前将非批量请求限制为 12 个高价值操作；修订 (revision) 仅返回变更行，未变更的操作在本地保留。

## CLI 工具

需要文件级产物、URL 审核附件、快照差异比较或更严格的离线规划时使用 CLI。

```bash
# 必须设置 PYTHONPATH，因为这是一个 src-layout 包。
PYTHONPATH=src python3 -m bookmark_advisor <command>
```

### 快照与审核

```bash
# 导出当前 Edge 书签
PYTHONPATH=src python3 -m bookmark_advisor export-snapshot

# 为公开 URL 构建审核队列
PYTHONPATH=src python3 -m bookmark_advisor build-review-queue \
  --snapshot data/snapshots/snapshot_YYYYMMDD_HHMMSS.json

# 将审核结果合并回快照
PYTHONPATH=src python3 -m bookmark_advisor enrich-snapshot \
  --snapshot data/snapshots/snapshot_YYYYMMDD_HHMMSS.json \
  --reviews data/reviews/url_review_YYYYMMDD_HHMMSS.json
```

### AI 规划

```bash
# 生成草稿方案（OpenAI 或兼容提供商）
OPENAI_API_KEY=... OPENAI_BASE_URL=https://your-provider.example.com/v1 \
PYTHONPATH=src python3 -m bookmark_advisor plan-ai \
  --snapshot data/snapshots/enriched_snapshot_YYYYMMDD_HHMMSS.json \
  --rules config/rules.yaml \
  --model gpt-5.4-mini

# 将草稿定稿为已审核方案
PYTHONPATH=src python3 -m bookmark_advisor finalize-plan \
  --input data/plans/draft_YYYYMMDD_HHMMSS.json

# 比较两个快照的差异
PYTHONPATH=src python3 -m bookmark_advisor diff-snapshot \
  --before data/snapshots/before.json --after data/snapshots/after.json
```

CLI 规划器使用官方 `openai` Python SDK。通过 `OPENAI_BASE_URL` 设置兼容提供商。自动回退链：`responses/json_schema → chat.completions/json_schema → chat.completions/json_object → chat.completions/plain_json`。

### 作业运行器 (Job Runner)

```bash
# 初始化整理作业
PYTHONPATH=src python3 -m bookmark_advisor init-job --workspace . --primary-backend extension

# 运行下一个待执行阶段
PYTHONPATH=src python3 -m bookmark_advisor run-job --job data/jobs/reorg_*/reorg-job.json
```

作业运行器按 export → review-queue → enrich → ai-plan → finalize 顺序逐步执行，带有文件锁和扩展等待阶段。

## 常用检查

```bash
# 完整测试套件
PYTHONPATH=src python3 -m pytest tests/

# 仅 Python CLI 测试
PYTHONPATH=src python3 -m unittest discover -s tests

# 聚焦扩展测试
python -m pytest tests/test_extension_service_worker_state.py \
  tests/test_extension_plan_lint.py \
  tests/test_extension_endpoint_urls.py \
  tests/test_extension_popup_state.py -x -q

# 语法检查已审核方案
python3 -m json.tool data/plans/reviewed_plan.json
```

## 项目结构

```
extension/          ← Edge MV3 扩展（原生 JS，无构建步骤）
src/bookmark_advisor/  ← Python CLI（setuptools src-layout）
config/rules.yaml   ← 安全护栏：保护路径、强制重定位、分类提示
skills/             ← Agent skills：书签整理和 URL 审核工作流
tests/              ← unittest/pytest 测试模块（CLI 和扩展行为）
data/               ← 运行时产物：快照、方案、作业（已 gitignore）
```

**数据流**：snapshot → review-queue → url-review → enriched-snapshot → draft-plan → reviewed-plan → execution-report。每个中间文件都是可读的 JSON，可直接编辑和复用。

**规则** (`config/rules.yaml`) 是安全护栏而非分类器：保护根目录、强制已知重定位、约束高风险操作，并默认将保护根目录下的散落书签保持原位。

## 更新日志

参见 [CHANGELOG.md](CHANGELOG.md)。
