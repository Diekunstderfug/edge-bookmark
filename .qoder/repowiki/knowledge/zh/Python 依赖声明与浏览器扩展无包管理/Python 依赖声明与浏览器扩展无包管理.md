---
kind: dependency_management
name: Python 依赖声明与浏览器扩展无包管理
category: dependency_management
scope:
    - '**'
source_files:
    - pyproject.toml
---

本项目采用双栈架构，依赖管理方式在两端差异显著：

## Python CLI（src/bookmark_advisor）
- **包管理器**：仅使用 `pyproject.toml` + setuptools 声明依赖，未使用 pipenv/poetry/uv 等现代工具。
- **依赖清单**：`pyproject.toml` 中 `dependencies = ["openai>=1.0.0"]`，仅声明一个运行时第三方库；其余均为 Python 标准库（json、pathlib、dataclasses、urllib.parse 等）。
- **构建系统**：`[build-system] requires = ["setuptools>=68"]`，后端为 `setuptools.build_meta`，通过 `[tool.setuptools.packages.find] where = ["src"]` 定位源码目录。
- **入口点**：`[project.scripts] bookmark-advisor = "bookmark_advisor.cli:main"` 暴露命令行。
- **版本锁定**：**不存在** `requirements.txt`、`poetry.lock`、`Pipfile.lock` 或 `uv.lock`，也未见 vendoring 策略。依赖版本以 `>=` 宽松约束声明，安装时由 pip 解析最新兼容版本。
- **可选导入**：`openai` 在 `ai_planner.py` 中以函数内 `from openai import OpenAI` 形式按需导入，避免在无 LLM 场景下启动失败。

## Edge MV3 扩展（extension/）
- **无包管理文件**：未发现 `package.json`、`yarn.lock`、`pnpm-lock.yaml`、`bun.lockb` 或任何 Node.js 依赖清单。
- **模块组织**：所有 JS 文件直接通过全局变量和条件式 `require()` 加载同仓库内的共享模块（如 `../shared/plan_schema.js`），属于“单仓直引”模式，不经过 npm/yarn 包分发。
- **浏览器 API**：依赖 Edge/Chrome 内置 API（`chrome.bookmarks`、`chrome.runtime`、`fetch`、`AbortController`），无需额外声明。
- **测试侧**：测试文件同样直接 `import` 本地 `.js` 模块，未见任何第三方 JS 库引用。

## 约定与风险
- Python 端缺少锁文件，CI 或协作环境可能出现依赖漂移；建议引入 `pip-tools` / `uv` / `poetry` 生成 lock 文件。
- JS 端完全零外部依赖是优势（体积小、可移植），但也不具备复用能力；若未来需要引入第三方库，应尽早统一选择 npm 生态并建立 lock 文件策略。