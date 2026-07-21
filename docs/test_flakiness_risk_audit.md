# 测试不稳定性（Flaky Tests）风险审查

日期：2026-05-17
范围：`tests/` 下 Python CLI + Extension(JS via Node subprocess) 测试

## 结论摘要

- **高风险（需优先治理）**：Node 子进程测试的超时阈值统一较短（10s/15s），在 CI 负载高或低性能机器上可能偶发超时失败。
- **中风险**：部分测试依赖运行时环境（`node` 可执行、Python/Node 行为差异、系统 locale/encoding），会导致“在某些机器总是失败/跳过”的非稳定表现。
- **中风险**：存在异步逻辑验证（service worker job / fetch / storage 回调）但多通过一次性 Promise 完成判定，边界 race 条件覆盖不足。
- **低风险**：测试整体随机性较低（未发现 `random`/`sleep`），大多数用 `TemporaryDirectory` 做隔离，顺序依赖相对可控。

## 风险明细（风险 + 证据 + 建议）

### 1) 时间依赖：Node 子进程 timeout 偏紧（高）

**证据**
- `tests/test_extension_endpoint_urls.py` 在 `_node_eval/_node_script` 中对子进程设置 `timeout=15`。 
- `tests/test_extension_service_worker_state.py` 对所有 Node 运行设置 `timeout=15`。
- `tests/test_url_parity.py` 在 `_run_js_fixtures` 中设置 `timeout=10`。

**风险说明**
- 这些测试加载较大 JS 文件（如 `service_worker.js`）并执行较多 mock/Promise 链，10-15 秒在拥塞 CI、CPU 限频、Windows runner 上容易偶发超时。
- 这类失败通常“重跑就过”，典型 flaky 特征。

**稳定化建议**
- 将 timeout 提高到更保守区间（例如 30-60 秒），并在失败日志输出实际耗时。
- 为 Node 测试增加轻量重试（仅对子进程 timeout 例外重试 1 次），避免瞬时抖动引发红灯。
- 将超时阈值参数化为环境变量（如 `EDGE_TEST_NODE_TIMEOUT_SEC`），便于 CI 分层调优。

### 2) 外部环境：Node 依赖与版本漂移（中）

**证据**
- 多个 extension 测试以 `@unittest.skipUnless(shutil.which("node"), ...)` 条件运行：
  - `tests/test_extension_plan_lint.py`
  - `tests/test_extension_service_worker_state.py`
  - `tests/test_extension_popup_state.py`
  - `tests/test_extension_endpoint_urls.py`
- `tests/test_url_parity.py` 也用 `_has_node()` 做条件跳过。

**风险说明**
- 在无 Node 的环境会被跳过，造成覆盖不一致；在不同 Node 版本上，URL/Promise/microtask 的细微行为变化可能导致偶发差异。

**稳定化建议**
- 固定 CI Node 主版本（如 20.x LTS）并在本地开发说明中写明最小版本。
- 在测试启动阶段打印 `node --version` 与 `python --version`，把环境差异转化为可追踪证据。
- 将“Node 缺失”从静默跳过升级为 CI 预检失败（在需要 extension 覆盖的 job 里）。

### 3) 并发/异步：后台任务即时返回与后续持久化判定（中）

**证据**
- `tests/test_extension_service_worker_state.py` 包含 `background_job_returns_immediately_then_persists_result` 等异步场景，依赖 mocked `fetch` + message listener + storage 回调完成时机。

**风险说明**
- 这类测试如果只断言最终状态，未显式约束中间状态时序，容易在事件循环调度差异下出现偶发行为（尤其在不同 Node/V8 版本）。

**稳定化建议**
- 引入显式“事件屏障”与阶段性断言（如先断言立即返回，再轮询/await 持久化完成标记）。
- 对关键异步路径增加 deterministic hooks（例如 test-only `await flushPendingTasks()`）。
- 统一 Promise 链结尾 `console.log` 输出结构，保证只在 fully-settled 后输出 JSON。

### 4) 顺序依赖：集合/字典比较与输出顺序（低-中）

**证据**
- `tests/test_rules_parity.py` 使用 `set(...)` 做键集合比较，降低顺序影响（正向）。
- 但仍有部分场景通过字符串/完整输出做断言（如 Node stdout 最后一行 JSON 解析策略）。

**风险说明**
- 若 stdout 混入额外日志（调试输出/警告），`last line JSON` 机制在某些场景可能误判。

**稳定化建议**
- 统一 Node test harness：stdout 仅输出一个 `RESULT_JSON:` 前缀行，再按前缀提取，避免日志污染。
- 对 map/object 结构断言尽量改为结构化字段断言，不依赖序列化顺序。

### 5) 随机性与 sleep 使用（低，当前较好）

**证据**
- 在 `tests/` 未检出 `random` 或 `sleep` 调用（本次检索范围内）。
- 大量测试使用 `TemporaryDirectory()` 做隔离，减少共享状态污染。

**风险说明**
- 当前无显式随机种子问题、无基于 sleep 的脆弱等待，基础稳定性较好。

**稳定化建议**
- 维持“禁止 sleep 等待”的测试规范，异步统一改为事件/状态条件等待。
- 如未来引入随机输入，必须固定 seed 并在失败日志回显 seed。

## 建议的治理优先级

1. **P0**：上调 Node 子进程 timeout（10/15s → 30/60s）+ timeout-only 重试一次。
2. **P1**：CI 固定 Node 版本并打印运行时版本信息。
3. **P1**：为 service worker 异步测试添加阶段性断言与 flush hook。
4. **P2**：规范 Node harness 输出前缀，消除 stdout 日志干扰。

## 复核命令（本次审查使用）

- `rg --files | rg 'AGENTS.md|tests|test_|pytest|unittest|sleep|time|random|thread|async|node|subprocess|order|flaky|retry|alarm'`
- `rg -n "sleep|time\.|datetime|date\(|random|shuffle|uuid|subprocess|node|Thread|thread|asyncio|alarm|retry|TemporaryDirectory|mkdtemp|cwd|os\.environ|PYTHONPATH|order|sorted\(|set\(|dict\(" tests`
- `sed -n '1,220p' tests/test_extension_endpoint_urls.py`
- `sed -n '1,220p' tests/test_extension_service_worker_state.py`
- `sed -n '1,220p' tests/test_url_parity.py`
- `sed -n '1,180p' tests/test_rules.py`
