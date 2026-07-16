# AI 接口测试 Agent 平台

## 开始任务前

1. 阅读 [开发设计文档.md](开发设计文档.md) 和 [开发步骤.md](开发步骤.md)，再检查 `git status --short`。
2. 仅完成用户指定的里程碑或子任务；语义、安全和数据边界不清晰时先询问。
3. 保留工作区已有改动，不假设规划中的模块或迁移已实际执行。

## 当前结构

| 路径 | 职责 |
| --- | --- |
| `backend/app/main.py` | FastAPI 生命周期、统一响应、错误与 `request_id`。 |
| `backend/app/common/` | 公共错误、响应、模型、网络目标校验与请求上下文。 |
| `backend/app/modules/` | auth、users、projects、environments、source_scans、knowledge、agents、testcases、executions、test_suites、reports、llm_configs。 |
| `backend/app/workers/task_worker.py` | PostgreSQL 单进程后台任务 Worker。 |
| `backend/alembic/versions/` | 迁移版本；最新为 `0018_add_execution_traceability_snapshots`。 |
| `frontend/src/api/` | 集中 API 封装与领域类型。 |
| `frontend/src/views/` | 登录、项目、接口、分析、用例、执行、流程与报告页面。 |
| `deploy/sql/001_init_business_schema.sql` | 历史全量建表脚本；实际初始化优先使用 Alembic 基线，不能在空库中无规划地同时执行两者。 |
| `docs/` | 交付说明和 MVP 验收用例。 |

## 关键约束

- 后端使用 Python 3.12、FastAPI、SQLAlchemy Async、Pydantic；Router 只处理 HTTP 边界，Service 管理业务事务，Repository 管理数据访问。
- 前端使用 Vue 3 Composition API、`<script setup lang="ts">`、TypeScript strict；禁止 `any`，请求只能放在 `frontend/src/api/`。
- 新增表结构必须新增 Alembic 迁移，不能改写已有版本；迁移不得依赖运行时 ORM。
- 密钥仅从 `.env` 读取。不得记录或返回密码、JWT、API Key、Cookie、完整源码或未脱敏请求响应。
- 源码只能访问 `SOURCE_ROOT_ALLOWLIST` 内目录或受控上传文件；禁止读取项目根目录外文件、执行任意 Shell 或自动执行未审核用例。
- 执行目标必须通过 Host 白名单和 DNS 公网地址校验；生产环境永远禁止执行；写请求必须确认完整目标 Host。
- `approved` 是唯一可执行用例状态。执行报告的追溯快照必须包含执行、用例、规则、符号、扫描、Prompt 和模型版本，且请求模板和断言配置必须脱敏。
- 保持最小修改，不重构当前任务无关模块，不新增不必要依赖、脚本、演示数据或文件。

## 已实现能力

- 用户认证、项目与项目权限、源码/OpenAPI 配置、环境和 LLM 配置。
- Java/Spring 源码扫描、OpenAPI 合并、知识切块与混合检索。
- Agent 分析、结构化用例生成、人工审核。
- 单用例/批量执行、变量替换、确定性断言、脱敏 cURL、SSE 状态。
- 顺序流程、变量提取、报告、失败重试、失败诊断和执行追溯快照。

## 命令

以下命令尚未在当前工作区验证。仅在用户当次明确授权安装、启动、迁移、构建或测试时执行。

| 位置 | 命令 | 用途 |
| --- | --- | --- |
| `backend/` | `uv sync` | 安装后端依赖。 |
| `backend/` | `uv run alembic -c alembic.ini upgrade head` | 执行迁移。 |
| `backend/` | `uv run uvicorn app.main:app --reload` | 启动后端。 |
| `backend/` | `uv run ruff check .` | Ruff 检查。 |
| `backend/` | `uv run mypy app` | Mypy 检查。 |
| `backend/` | `uv run pytest` | 后端测试。 |
| `frontend/` | `pnpm install` | 安装前端依赖。 |
| `frontend/` | `pnpm dev` | 启动 Vite。 |
| `frontend/` | `pnpm typecheck` | Vue TypeScript 检查。 |
| `frontend/` | `pnpm build` | 前端生产构建。 |

当前 M7 交付不包含 Docker Compose 部署或启动；不得在未获得明确授权时执行 Docker 命令。

## 完成后

报告修改文件、实现内容、实际执行的验证以及未验证风险。默认不运行安装、构建、测试、迁移、Docker 或服务启动。
