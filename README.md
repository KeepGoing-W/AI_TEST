# AI 接口测试 Agent 平台

面向 Java/Spring Boot REST API 的 AI 测试平台。平台从受控源码与 OpenAPI 中生成可审核用例，以确定性执行器运行接口和流程测试，并保留脱敏的执行证据与追溯快照。

当前已完成 M0-M7 的代码实现。M7 的 Docker Compose 部署按当前交付范围暂不提供；本说明仅覆盖本地/受控环境交付。

## 文档

- [交付与操作说明](docs/交付与操作说明.md)：环境变量、初始化管理员、迁移、扫描与执行流程。
- [MVP 验收用例](docs/MVP验收用例.md)：AC-001 至 AC-005 的验收步骤与预期结果。
- [开发设计文档](开发设计文档.md)：产品范围和安全边界。
- [开发步骤](开发步骤.md)：里程碑拆分。

## 工程结构

- `backend/`：FastAPI、异步 SQLAlchemy、Alembic、后台 Worker、Agent、执行器和报告模块。
- `frontend/`：Vue 3 管理台，包含项目、接口、分析、用例、执行、流程和报告页面。
- `deploy/`：数据库初始化脚本。
- `docs/`：交付和验收文档。

## 本地交付前提

- Python 3.12、uv、Node.js 22 LTS、pnpm。
- 可访问的 PostgreSQL 16 + pgvector 实例。
- 已安装 `ripgrep`，供受控源码精确检索使用。

将 `.env.example` 复制为 `.env`，填写真实密钥和数据库地址。`.env` 不得提交到仓库。

```powershell
Copy-Item .env.example .env
```

然后按 [交付与操作说明](docs/交付与操作说明.md) 执行依赖安装、迁移和服务启动。以下命令尚未在本工作区重新验证，需由交付人员在受控环境中执行：

```powershell
Set-Location backend
uv sync
uv run alembic -c alembic.ini upgrade head
uv run uvicorn app.main:app --reload
```

```powershell
Set-Location frontend
pnpm install
pnpm dev
```

## 安全边界

- 仅扫描登记在 `SOURCE_ROOT_ALLOWLIST` 中的本地目录，ZIP 拒绝路径越界和符号链接条目。
- 执行目标必须属于环境 Host 白名单，解析到私网/保留地址或出现 DNS 解析变化时会被拒绝。
- OpenAPI URL 必须位于 `OPENAPI_HOST_ALLOWLIST`，并经过相同的受控网络校验。
- 生产环境禁止执行；写请求必须确认完整目标 Host。
- 仅 `approved` 用例可以执行；报告、cURL、变量和请求响应证据会脱敏。

## 验收与验证

交付前按 [MVP 验收用例](docs/MVP验收用例.md) 覆盖 AC-001 至 AC-005。静态检查与测试命令见 `AGENTS.md`；它们不会由本项目文档自动执行。
