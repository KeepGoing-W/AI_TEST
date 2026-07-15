# AI 接口测试 Agent 平台

面向 Java/Spring Boot REST API 的 AI 测试平台。平台基于真实源码和 OpenAPI 生成可审核、可执行、可追溯的测试用例，并由确定性执行器完成接口调用和断言。

## 当前进度

当前处于 M0-3 数据库与迁移基础阶段：已建立后端骨架、异步数据库访问、Alembic 迁移和 PostgreSQL + pgvector 配置；尚未创建业务表、认证、前端或业务模块。

## 目录说明

- `backend/`：FastAPI 后端工程。
- `frontend/`：Vue 3 前端工程。
- `deploy/`：部署配置。
- `docs/`：项目文档。

## 环境变量

复制 `.env.example` 为 `.env` 后再填写真实密钥。`.env` 不应提交到仓库。
