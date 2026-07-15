# AI 接口测试 Agent 平台

## 开始任务前

1. 阅读 [开发设计文档.md](开发设计文档.md) 和 [开发步骤.md](开发步骤.md)。前者定义 MVP 范围与安全边界，后者定义当前开发阶段。
2. 检查工作区和 `git status --short`；不要假设规划中的模块已经存在。
3. 每次只完成用户明确指定的一个阶段或子任务。需求存在语义、安全或数据边界歧义时，先询问，不自行扩展范围。

## 当前结构

| 路径 | 职责 |
| --- | --- |
| `backend/app/main.py` | FastAPI 入口、生命周期、统一错误和 `request_id` 中间件 |
| `backend/app/common/` | 公共错误、响应、模型基类和请求上下文 |
| `backend/app/modules/auth/` | JWT、密码散列、登录、当前用户和鉴权依赖 |
| `backend/app/modules/users/` | 用户模型、数据访问、服务和管理员用户接口 |
| `backend/alembic/` | 异步 Alembic 配置与迁移版本 |
| `frontend/src/api/` | 集中 API 请求封装 |
| `frontend/src/stores/` | Pinia 跨页面状态 |
| `frontend/src/router/` | Vue Router 和登录守卫 |
| `frontend/src/layouts/` | 管理台基础布局 |
| `frontend/src/views/` | 登录页和项目管理空页 |
| `frontend/src/styles/` | 全局 Token、重置和通用样式 |
| `deploy/sql/001_init_business_schema.sql` | PostgreSQL 16 + pgvector 全量业务建表脚本 |
| `docker-compose.yml` | 仅 PostgreSQL + pgvector 服务 |

## 已实现 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 基础健康检查 |
| `POST` | `/api/v1/auth/login` | 用户登录，返回 JWT |
| `GET` | `/api/v1/auth/me` | 当前用户 |
| `POST` | `/api/v1/users` | 管理员创建用户 |
| `PATCH` | `/api/v1/users/{user_id}/status` | 管理员启用或禁用用户 |

成功响应固定为 `data`、`message`、`requestId`；错误响应固定为 `code`、`message`、`details`、`requestId`。前端只能依据稳定错误码处理逻辑，不能依赖中文错误文案。

## 后端规则

- 使用 Python 3.12、FastAPI、SQLAlchemy Async 和 Pydantic。所有对外函数声明参数与返回类型。
- Router 只负责 HTTP 边界；业务事务放在 Service；数据访问放在 Repository；不要在 Router 编写业务逻辑。
- 新增实体继承 `Base`，按需组合 `UUIDPrimaryKeyMixin` 与 `TimestampMixin`。核心关系使用外键；JSONB 仅存放结构不稳定数据。
- 表结构变更必须新增 Alembic 迁移，不能改写已存在的迁移版本；迁移不能依赖运行时 ORM 状态。
- 密码使用 `pwdlib[argon2]`；JWT 密钥和初始化管理员密码只从 `.env` 读取，不能写入日志、响应或仓库。
- 未启用用户、无效 Token 和无管理员权限必须返回稳定业务错误码。
- 只使用受控数据访问和受控网络目标；后续 Agent 不得读取项目根目录外文件、执行 Shell、直接操作数据库或自动执行未审核用例。

## 前端规则

- 使用 Vue 3 Composition API、`<script setup lang="ts">` 和 TypeScript strict；禁止 `any`。
- 跨页面认证和任务状态放在 Pinia，局部交互状态保留在组件。
- 所有 HTTP 请求放在 `frontend/src/api/`；不直接在页面组件内创建请求客户端。
- 使用 `frontend/src/styles/tokens.css` 中的 Token；不要在组件中散落硬编码颜色、间距和圆角。
- 管理台视觉遵循冷灰白底、弱阴影、紫色状态轨道。紫色仅用于当前项、智能状态和主要操作。
- 未实现的业务功能不得提供可操作入口。当前仅显示项目管理入口和其空状态。
- 交互元素必须保留键盘焦点样式，动画应尊重 `prefers-reduced-motion`。

## 数据库与初始化

- PostgreSQL 服务使用 `pgvector/pgvector:pg16`，数据库时间使用 UTC。
- `.env.example` 仅为字段模板。复制为 `.env` 后，必须设置真实的 `POSTGRES_PASSWORD`、`JWT_SECRET` 和 `INITIAL_ADMIN_PASSWORD`；不得提交 `.env`。
- `deploy/sql/001_init_business_schema.sql` 是全量建表脚本，当前 Alembic 迁移仅覆盖 pgvector 扩展和 `users` 表。实际初始化数据库前，必须先统一这两条基线，不能在同一空库中不加规划地同时执行两者。
- 执行记录需要保留快照。后续删除或禁用用例时，不得破坏既有执行历史。

## 命令

以下命令来自当前配置文件，尚未在本工作区验证。仅在用户当次明确授权安装、启动、迁移、构建或测试时执行。

| 位置 | 命令 | 用途 |
| --- | --- | --- |
| 根目录 | `docker compose up -d postgres` | 启动 PostgreSQL + pgvector |
| `backend/` | `uv sync` | 安装后端依赖 |
| `backend/` | `uv run uvicorn app.main:app --reload` | 启动后端 |
| `backend/` | `uv run alembic -c alembic.ini upgrade head` | 执行迁移 |
| `backend/` | `uv run ruff check .` | Ruff 检查 |
| `backend/` | `uv run mypy app` | Mypy 检查 |
| `backend/` | `uv run pytest` | 后端测试 |
| `frontend/` | `pnpm install` | 安装前端依赖 |
| `frontend/` | `pnpm dev` | 启动 Vite 开发服务 |
| `frontend/` | `pnpm typecheck` | Vue TypeScript 检查 |
| `frontend/` | `pnpm build` | 前端生产构建 |

## 修改边界

- 回复和产品文案使用中文；代码注释仅在解释关键业务原因时使用中文。
- 保持最小修改，不重构或优化当前任务无关模块，不引入未被当前阶段使用的依赖。
- 不创建演示数据、临时脚本或无关文档。
- 默认不运行安装、构建、测试、迁移、Docker 或服务启动。完成后报告修改文件、未执行验证和剩余风险。
