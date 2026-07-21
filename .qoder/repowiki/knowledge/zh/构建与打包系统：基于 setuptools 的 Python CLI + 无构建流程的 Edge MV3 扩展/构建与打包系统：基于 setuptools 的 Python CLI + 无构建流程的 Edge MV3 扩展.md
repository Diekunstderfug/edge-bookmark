---
kind: build_system
name: 构建与打包系统：基于 setuptools 的 Python CLI + 无构建流程的 Edge MV3 扩展
category: build_system
scope:
    - '**'
source_files:
    - pyproject.toml
    - src/bookmark_advisor/cli.py
    - extension/manifest.json
    - tests/AGENTS.md
    - AGENTS.md
    - README.md
---

本仓库采用“双产物、极简构建”策略：Python CLI 通过标准 setuptools 打包，Edge 扩展为纯 JS/HTML/CSS 源码直接加载，无需编译或打包步骤。

## 1. 使用的系统与工具
- **Python 包管理**：`pyproject.toml` + `setuptools.build_meta`（要求 setuptools ≥68），Python ≥3.9。
- **入口点**：通过 `[project.scripts]` 注册 `bookmark-advisor` 命令行，指向 `bookmark_advisor.cli:main`。
- **测试**：CLI 侧使用 stdlib `unittest`（`python3 -m unittest discover -s tests`），扩展行为侧使用 `pytest`（需 Node.js 运行子进程模拟 `chrome` 全局）。
- **代码质量缓存**：`.gitignore` 忽略 `.mypy_cache/`、`.ruff_cache/`、`.coverage`，表明项目期望使用 mypy、ruff、coverage，但当前仓库未提供对应配置文件。
- **扩展构建**：明确声明“no npm/node, no package.json”，Edge MV3 扩展以源码形式由浏览器直接加载，无任何前端构建管线。

## 2. 关键文件
- `pyproject.toml` — 唯一构建元数据，定义包名、版本、依赖、脚本入口、包发现规则。
- `src/bookmark_advisor/__init__.py` / `__main__.py` / `cli.py` — Python 包结构与 CLI 入口。
- `extension/manifest.json` — MV3 扩展清单，描述 Service Worker、Offscreen Document、权限等。
- `tests/` — 按模块划分的测试集，命名约定 `test_extension_*.py` 对应扩展组件。
- `AGENTS.md` / `README.md` — 记录本地开发命令与“无 CI/CD”现状。

## 3. 架构与约定
- **包布局**：`src/` 下放置可安装包，`pyproject.toml` 中 `[tool.setuptools.packages.find].where = ["src"]` 控制发现。
- **版本管理**：版本号硬编码在 `pyproject.toml` 的 `[project] version = "0.1.0"`，未见自动化 bump 机制。
- **依赖管理**：仅声明运行时依赖 `openai>=1.0.0`；开发期工具（mypy/ruff/pytest）未写入依赖清单，开发者自行安装。
- **测试隔离**：CLI 测试用 unittest，扩展测试用 pytest 并 spawn Node 子进程注入 mock chrome 环境，两者通过 `PYTHONPATH=src` 共享源码。
- **发布工件**：无 Dockerfile、无 Makefile、无 CI 流水线；文档明确“No CI/CD pipeline”，发布前仅手动执行语法检查与测试。

## 4. 开发者应遵循的规则
- 修改 Python 包后，始终通过 `PYTHONPATH=src python3 -m unittest discover -s tests` 运行 unittest 用例，或通过 `python -m pytest tests/test_extension_*.py` 运行扩展相关测试。
- 不要引入 npm/node 依赖或前端构建步骤；扩展代码保持纯 JS，直接由 Edge 加载。
- 新增 Python 依赖时同步更新 `pyproject.toml` 的 `dependencies`，以便 `pip install .` 能复现环境。
- 如需引入 mypy/ruff/black 等工具，先在仓库根添加对应配置（如 `pyproject.toml` 中的 `[tool.mypy]`、`[tool.ruff]`），再统一纳入工作流。
- 版本号变更需在 `pyproject.toml` 中手动调整，目前无自动化版本提升流程。