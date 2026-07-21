---
kind: configuration_system
name: 配置系统 — YAML/JSON 规则文件与浏览器存储分层持久化
category: configuration_system
scope:
    - '**'
source_files:
    - config/rules.yaml
    - src/bookmark_advisor/rules.py
    - extension/fast_rules.json
    - extension/popup/settings_store.js
    - extension/shared/storage.js
    - extension/shared/ai_endpoint.js
    - src/bookmark_advisor/ai_planner.py
    - pyproject.toml
---

## 1. 整体方案
本项目采用「双端独立」的配置体系：
- Python CLI 侧通过 `config/rules.yaml`（或 workspace 下的同名文件）加内置轻量 YAML 解析器，配合 `pyproject.toml` 的脚本入口完成启动参数注入。
- Edge MV3 扩展侧通过 `chrome.storage.local` / `chrome.storage.sync` 持久化用户偏好、LLM 设置与 UI 草稿，并通过 `extension/shared/ai_endpoint.js` 提供默认 API 基址与风格常量。
- 两套配置在结构上保持对称：`config/rules.yaml` 与 `extension/fast_rules.json` 字段完全一致，分别供 Python 与 JS 侧使用。
- 运行时敏感信息（OpenAI Key、Base URL、Organization、Project）仅通过环境变量加载，不写入任何持久化存储。

## 2. 关键文件与包
- `config/rules.yaml` — 规则定义主文件（defaults / category_hints / folder_relocations / bookmark_relocations / protected_paths）
- `src/bookmark_advisor/rules.py` — 规则加载、路径解析、严格校验与内置 YAML 解析器
- `extension/fast_rules.json` — 与 rules.yaml 同构的 JSON 版本，供扩展快速加载
- `extension/popup/settings_store.js` — LLM 设置、用户偏好、UI 草稿的持久化与归一化
- `extension/shared/storage.js` — chrome.storage.local 的 Promise 封装
- `extension/shared/ai_endpoint.js` — OpenAI 兼容端点的默认值、URL 拼接、超时钳制等纯函数
- `src/bookmark_advisor/ai_planner.py` — CLI 调用 LLM 时从环境变量读取 OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_ORGANIZATION / OPENAI_PROJECT / OPENAI_API_STYLE
- `pyproject.toml` — 项目元数据与 `bookmark-advisor` 脚本入口

## 3. 架构与约定
### 3.1 规则文件（rules.yaml / fast_rules.json）
- 顶层键白名单：`defaults`、`category_hints`、`folder_relocations`、`bookmark_relocations`、`protected_paths`；未知键直接报错。
- `defaults.protect_root_loose_bookmarks` 与 `allow_new_folders_in_advise` 为布尔开关；`generic_new_folder_names` 为字符串列表。
- `bookmark_relocations[].match` 支持 `folder_path`、`title_contains`、`title_equals`、`url_contains` 四个匹配条件，至少声明一个。
- 路径解析优先级：命令行 `--rules` → workspace/config/rules.yaml → 仓库根 config/rules.yaml；未找到则抛错。
- 解析器为手写轻量实现，不支持 tab 缩进，仅支持标量、嵌套映射与列表，且自动识别首行 `{` 走 JSON 分支，因此 `fast_rules.json` 可被同一套逻辑消费。

### 3.2 浏览器扩展配置（settings_store.js）
- 三类配置对象：`llmSettings`（apiBaseUrl/apiStyle/model/requestTimeout）、`preferences`（protectRootLooseBookmarks/sortOrder/planningStyle/lang）、`uiDraft`（activeTab/focusPath/maxActions/maxRetries/userInstruction）。
- 所有字段均有默认值并在写入前做归一化（类型转换、枚举校验、HTTPS 校验、超时钳制到 MAX_REQUEST_TIMEOUT_MS）。
- `preferences` 优先写入 `chrome.storage.sync`，失败回退到 `local`；`llmSettings` 与 `uiDraft` 始终写 `local`。
- `apiBaseUrl` 必须为 https:// URL，并据此动态申请 host permission（`permissions.contains` / `permissions.request`）。
- `STORAGE_KEYS` 由共享协议集中管理，避免硬编码 key 散落在各处。

### 3.3 环境变量（CLI 侧）
- `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_ORGANIZATION`（或 `OPENAI_ORG_ID`）、`OPENAI_PROJECT`、`OPENAI_API_STYLE` 五个变量用于覆盖 CLI 传入的 `--base-url` / `--api-style` / `--model` 等参数。
- 无 `.env` 文件加载逻辑，依赖外部 shell 或进程环境注入。

## 4. 开发者应遵循的规则
1. **新增规则字段**：同步修改 `ALLOWED_TOP_LEVEL_KEYS` / `ALLOWED_DEFAULT_KEYS` / `ALLOWED_MATCH_KEYS` 及对应的 `_build_rules_config` 构造逻辑，并在 `validate_rules_data` 中补充类型检查。
2. **新增用户偏好**：在 `settings_store.js` 的 `defaultPreferences` 中添加默认值，在 `normalizePreferences` 中增加枚举白名单校验，并在 `loadPreferences`/`savePreferences` 中透传。
3. **新增 LLM 设置项**：在 `DEFAULT_LLM_SETTINGS` 与 `normalizeLlmSettings` 中配对添加，确保 `aiEndpoint.normalize*` 工具函数可用。
4. **新增环境变量**：仅在 `ai_planner.py` 中读取，不要写入任何持久化存储；同时在 `cli.py` 对应子命令的参数中暴露同名 `--xxx` 选项以便显式覆盖。
5. **保持 rules.yaml 与 fast_rules.json 同构**：新增一条重定向规则时，两个文件需同步更新，或通过生成脚本保证一致性。
6. **禁止硬编码 HTTPS 基址**：统一通过 `ai_endpoint.DEFAULT_API_BASE_URL` 与 `normalizeBaseUrl` 处理，避免绕过 origin 提取与权限检查。