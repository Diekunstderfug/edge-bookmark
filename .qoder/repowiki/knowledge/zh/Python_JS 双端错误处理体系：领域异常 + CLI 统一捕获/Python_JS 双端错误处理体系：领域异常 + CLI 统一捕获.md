---
kind: error_handling
name: Python/JS 双端错误处理体系：领域异常 + CLI 统一捕获
category: error_handling
scope:
    - '**'
source_files:
    - src/bookmark_advisor/rules.py
    - src/bookmark_advisor/ai_planner.py
    - src/bookmark_advisor/cli.py
---

## 1. 系统概览
本项目采用 Python（CLI 与核心逻辑）+ Edge MV3 扩展（浏览器前端）的双语言架构，错误处理策略在两端分别实现：
- Python 侧：定义领域异常类，通过 `raise` 向上抛出，由 CLI 顶层 `try/except` 集中捕获并输出到 stderr，返回非零退出码。
- JS 侧：基于 Promise/async 的异步调用链，错误通过 `.catch()` 或 `try/catch` 向上传播至 UI 层展示。

## 2. 关键文件与包
- `src/bookmark_advisor/rules.py` — 定义 `RulesValidationError(ValueError)`，用于规则文件校验失败。
- `src/bookmark_advisor/ai_planner.py` — 定义 `AIPlannerError(RuntimeError)`，封装 OpenAI SDK 不可用、API Key 缺失、JSON 解析失败、兼容性回退耗尽等 AI 规划阶段错误。
- `src/bookmark_advisor/cli.py` — 所有子命令入口，在每个命令分支内对已知异常类型进行 `except` 捕获，打印消息后 `return 1`。
- `extension/background/*.js`、`extension/popup/*.js`、`extension/ai/provider_client.js` — JS 端通过 Promise `.catch()` 和 `try/catch` 捕获网络/存储/计划执行错误，交由 UI 层提示用户。

## 3. 架构与约定
- **领域异常分层**：业务语义错误使用自定义异常子类（`RulesValidationError`、`AIPlannerError`），底层 I/O/解析错误使用标准异常（`FileNotFoundError`、`json.JSONDecodeError`、`ValueError`、`ImportError`）。CLI 层按语义粒度区分处理。
- **OpenAI 兼容性与重试**：`_request_semantic_plan` 内部维护 `COMPATIBILITY_FALLBACK_STATUS_CODES` 与 `NON_RETRYABLE_STATUS_CODES` 集合，自动在 `responses` / `chat_completions` 多种 API 风格间回退；遇到 401/403/429 直接抛错，不重试。
- **CLI 作为错误边界**：`cli.main()` 中每个子命令分支都包裹 `try/except`，将结构化异常转换为人类可读文本输出到 stderr，并以退出码 1 表示失败。未捕获的 `Exception` 仅打印字符串，避免崩溃。
- **无全局中间件**：Python 端没有类似 FastAPI 的错误中间件，错误传播是显式的函数级 `raise` + 调用方 `except`；JS 端依赖 Promise 链式 `.catch()` 而非全局 `unhandledrejection`。
- **无 panic/recover 等价物**：Python 不使用 `sys.exit()` 中断流程，也不使用 `try/finally` 做资源恢复；JS 端不使用 `throw new Error` 配合全局 handler，而是逐层 `.catch()`。

## 4. 开发者应遵循的规则
1. **新增业务错误时定义专用异常类**：继承自合适的内置异常（如 `ValueError`、`RuntimeError`），并在 docstring 中说明触发条件。
2. **不要在库函数中吞掉异常**：让异常冒泡到 CLI 或上层调用者统一处理；仅在需要包装上下文信息时使用 `from exc` 保留堆栈。
3. **CLI 层只负责“翻译”异常**：不要修改异常内容，仅将其转为字符串输出到 stderr 并返回非零退出码。
4. **OpenAI 相关错误一律走 `AIPlannerError`**：包括 SDK 缺失、环境变量缺失、HTTP 状态码、JSON 解析失败等，保持调用方单一 catch 点。
5. **JS 端使用 Promise `.catch()` 收集错误**：避免裸 `throw`，确保错误能传递到 UI 层；对于可恢复的网络错误，优先使用重试而非立即报错。
6. **避免 `except Exception` 泛化捕获**：在业务逻辑中尽量捕获具体异常类型，仅在 CLI 顶层使用泛化捕获兜底。