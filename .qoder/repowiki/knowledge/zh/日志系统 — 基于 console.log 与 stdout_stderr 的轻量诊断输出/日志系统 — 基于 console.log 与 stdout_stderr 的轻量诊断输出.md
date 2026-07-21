---
kind: logging_system
name: 日志系统 — 基于 console.log 与 stdout/stderr 的轻量诊断输出
category: logging_system
scope:
    - '**'
source_files:
    - src/bookmark_advisor/cli.py
    - extension/service_worker.js
    - extension/background/job_lifecycle.js
    - extension/background/message_router.js
    - src/bookmark_advisor/reporting.py
---

本项目未引入专用日志框架（如 Python logging、loguru、structlog），而是采用最轻量的双通道输出：Python CLI 使用 print 与 sys.stderr，Edge 扩展 Service Worker 使用 console.log。两者均无结构化字段、无级别控制、无集中 sink，属于开发期诊断与命令行产物风格。

1. 使用的系统与工具
- Python 侧：标准库 print 与 sys.stderr，用于命令输出与错误信息；无 logging 模块导入。
- JS 侧：console.log 作为唯一运行时日志出口，通过一个薄包装函数 swLog 统一注入到各后台模块。

2. 关键文件与位置
- src/bookmark_advisor/cli.py：所有子命令的主入口，成功路径用 print(...) 输出 JSON 路径或结果，异常路径用 print(str(exc), file=sys.stderr) 输出错误并返回非零退出码。
- extension/service_worker.js：定义 swLog(...args)，在浏览器环境调用 console.log(...args)，在 Node 测试环境下为空实现；该函数被注入到 JobLifecycle、MessageRouter 等模块。
- extension/background/job_lifecycle.js：通过构造参数 log = typeof options.log === 'function' ? options.log : function () {} 接收 logger，内部以 [BookmarkAdvisor][SW] ... 前缀记录恢复、心跳、失败等事件。
- extension/background/message_router.js：通过 createLogger(options.logger || options.log) 适配任意 { error } 对象或裸函数，并在 respondAsync 中包裹 try/catch，确保诊断日志不会阻断 sendResponse。
- src/bookmark_advisor/reporting.py：不产生控制台日志，但把计划执行结果写入 Markdown 报告文件，是“可归档的诊断工件”。

3. 架构与约定
- 无全局 logger 实例：JS 端通过依赖注入将 swLog 传入 JobLifecycle.create({ log: swLog })，再由 MessageRouter.create({ logger: reportProgress }) 复用同一接口。
- 日志格式约定：Service Worker 侧统一以 [BookmarkAdvisor][SW] <tag>: <message> 前缀标记来源，便于在 DevTools 中过滤。
- 错误输出分离：CLI 正常结果走 stdout，错误/校验失败走 stderr，配合 return 1 让上层脚本感知失败。
- 进度与结果持久化：运行期进度通过 STORAGE.set(PROGRESS, { message, updated_at }) 写入扩展存储，由 popup 轮询展示；最终报告落盘为 Markdown，不属于实时日志流。

4. 开发者应遵循的规则
- 新增诊断输出时，优先使用已注入的 log(message) 接口（JS）或 print(..., file=sys.stderr)（Python），不要自行创建新的全局 logger。
- JS 侧日志消息建议带上 [BookmarkAdvisor][SW] <组件名> 前缀，保持可读性与可过滤性。
- 不要在日志中输出敏感信息（API key、完整书签 URL 等）；需要保留上下文时使用结构化 JSON 工件（plan/report/snapshot）。
- 如需分级或结构化日志，应在 service_worker.js 的 swLog 处统一升级，再向下游注入，避免散点式 console.* 调用。