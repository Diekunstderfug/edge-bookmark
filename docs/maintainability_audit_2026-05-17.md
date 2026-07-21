# 可维护性与模块边界审查（2026-05-17）

## 审查范围
- Python CLI：`src/bookmark_advisor/cli.py`
- 作业编排：`src/bookmark_advisor/job_runner.py`
- 对照文档：`README.md`、`AGENTS.md`

## 1) 边界问题（模块职责是否清晰）

### 问题 1：`cli.py` 同时承载“命令定义 + 业务执行 + 序列化拼装”，边界偏厚
- 现象：`main()` 在一个函数内既定义全部 subcommands，又直接执行备份、规则加载、快照导出、AI 规划、计划落盘、执行应用等。  
- 影响：
  - 命令入口与业务逻辑耦合，新增子命令时需要修改同一大函数，回归面大；
  - 测试粒度更粗（多为集成路径），难对命令处理器做精细单测。
- 证据：`main()` 从参数定义一路延伸到多分支业务处理（`backup/advise/merge/apply/...`）。

### 问题 2：`job_runner.py` 中 phase 机与后端执行语义交织，状态域与执行域边界不够“声明式”
- 现象：同一循环中既处理阶段推进，也处理 `extension` 与 `write_source` 的执行差异；`extension` 路径推进到 `waiting_for_extension_execution` 后返回，`write_source` 路径则直接进入 `done`。  
- 影响：
  - phase 定义和 backend 行为绑定在同一层，后续扩展更多 backend 时易膨胀；
  - 状态机可读性依赖分支顺序，非表驱动。
- 证据：`PHASES` 定义 + `apply` 分支里分后端处理。

## 2) 关键耦合点

1. **CLI 与内部模块的高扇入耦合**  
   `cli.py` 顶层直接 import 大量子模块（planner、rules、snapshot_io、executor、job_runner 等），导致入口模块成为“知识汇聚点”。

2. **`job_runner` 对 AI 规划与规则解析的直接耦合**  
   在 `plan` 阶段直接调用 `plan_with_openai`，并在函数内部延迟导入 `load_rules`，体现运行时依赖拼接，降低依赖可见性。

3. **文件工件命名耦合**  
   `init_reorg_job()` 将 `snapshot.json / review-queue.json / url-review.json / ...` 作为固定路径写入清单，CLI/外部工具需遵守同名约定。

## 3) 与文档 / AGENTS 约定一致性评估

### 一致项
- 使用 `openai` SDK 的 CLI AI 规划路径，与 README 说明一致。
- Job runner 具备 file lock 与 extension waiting phase，与 README 文案一致。
- 默认模型 `gpt-5.4-mini` 与 README/AGENTS 一致。

### 不一致 / 易混淆项
1. **阶段命名口径不统一（文档语义名 vs 代码内部名）**
   - README 使用语义阶段：`export → review-queue → enrich → ai-plan → finalize`；
   - 代码使用内部状态：`snapshot → review → enrich → plan → finalize → apply → waiting_for_extension_execution`。  
   这不是功能错误，但会增加排障沟通成本（尤其跨 CLI / extension / 文档）。

2. **AGENTS “phase machine”示例序列含 `execute`，代码里对应为 `apply` / `waiting_for_extension_execution`**
   - AGENTS 描述序列：`... → finalize → execute`；
   - 代码状态名无 `execute`，以 `apply` + `waiting_for_extension_execution` 表达。  
   建议统一术语映射，避免团队成员误判状态含义。

## 4) 改进建议（按投入/收益排序）

1. **拆分 CLI 命令处理器（高收益）**
   - 将 `main()` 中每个 command 分支提取为独立函数（如 `handle_export_snapshot(args)`）；
   - 仅在 `main()` 做参数解析与 dispatch。

2. **将 `job_runner` 状态机改为“phase handler 注册表”（中高收益）**
   - 使用 `{phase: handler}` + 统一返回 `(next_phase, message, status)`；
   - backend 策略抽象为 executor adapter（`ExtensionExecutor`, `WriteSourceExecutor`）。

3. **建立阶段术语映射表（低成本高沟通收益）**
   - 在 README 与 AGENTS 增加表格：`export=snapshot`、`ai-plan=plan`、`execute=apply/waiting_for_extension_execution`；
   - run-job 输出中可附带 `phase_alias` 字段，减少前端/脚本解析歧义。

4. **显式化延迟导入策略（中成本）**
   - 若保留 `from bookmark_advisor.rules import load_rules` 的函数内导入，请在注释中说明原因（循环依赖/启动性能）；
   - 或统一顶层导入，提升静态可读性与 IDE 可追踪性。
