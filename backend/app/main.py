import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.common.errors import AppError
from app.common.request_context import request_id_context
from app.common.responses import error_response, success_response
from app.config import get_settings
from app.database import engine, async_session_factory
from app.modules.auth.router import router as auth_router
from app.modules.agents.router import router as agents_router
from app.modules.agents.service import fail_interrupted_agent_runs
from app.modules.environments.router import router as environments_router
from app.modules.executions.router import router as executions_router
from app.modules.llm_configs.router import router as llm_configs_router
from app.modules.knowledge.router import router as knowledge_router
from app.modules.projects.router import router as projects_router
from app.modules.reports.router import router as reports_router
from app.modules.source_scans.router import router as source_scans_router
from app.modules.testcases.router import router as testcases_router
from app.modules.test_suites.router import router as test_suites_router
from app.modules.users.router import router as users_router
from app.modules.users.service import initialize_admin_user
from app.workers.task_worker import TaskWorker

logger = logging.getLogger(__name__)
settings = get_settings()

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """初始化管理员，并在服务退出时释放数据库连接。"""

    async with async_session_factory() as session:
        await initialize_admin_user(session)
        # 运行中的 LLM 调用无法在进程重启后安全续接，因此明确标记失败；待审核草稿保持可审核。
        await fail_interrupted_agent_runs(session)
    worker = TaskWorker()
    worker_task = asyncio.create_task(worker.run())
    try:
        yield
    finally:
        worker.stop()
        await worker_task
        await engine.dispose()


app = FastAPI(title="AI 接口测试 Agent 平台", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(agents_router, prefix=settings.api_v1_prefix)
app.include_router(environments_router, prefix=settings.api_v1_prefix)
app.include_router(executions_router, prefix=settings.api_v1_prefix)
app.include_router(llm_configs_router, prefix=settings.api_v1_prefix)
app.include_router(knowledge_router, prefix=settings.api_v1_prefix)
app.include_router(projects_router, prefix=settings.api_v1_prefix)
app.include_router(reports_router, prefix=settings.api_v1_prefix)
app.include_router(source_scans_router, prefix=settings.api_v1_prefix)
app.include_router(testcases_router, prefix=settings.api_v1_prefix)
app.include_router(test_suites_router, prefix=settings.api_v1_prefix)
app.include_router(users_router, prefix=settings.api_v1_prefix)


@app.middleware("http")
async def add_request_id(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """为每个请求绑定唯一标识，并在响应头返回。"""

    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = request_id
    context_token = request_id_context.set(request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        request_id_context.reset(context_token)


@app.exception_handler(AppError)
async def handle_app_error(request: Request, exc: AppError) -> Response:
    """返回稳定的业务错误码。"""

    return error_response(
        code=exc.code,
        message=exc.message,
        details=exc.details,
        request_id=request.state.request_id,
        status_code=exc.status_code,
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> Response:
    """返回请求参数校验错误。"""

    return error_response(
        code="REQUEST_VALIDATION_ERROR",
        message="请求参数校验失败",
        details={"errors": exc.errors()},
        request_id=request.state.request_id,
        status_code=422,
    )


@app.exception_handler(Exception)
async def handle_internal_error(request: Request, exc: Exception) -> Response:
    """隐藏未知异常细节，仅记录受保护日志。"""

    logger.exception("未处理的服务端异常，request_id=%s", request.state.request_id, exc_info=exc)
    return error_response(
        code="INTERNAL_ERROR",
        message="服务内部错误",
        request_id=request.state.request_id,
        status_code=500,
    )


@app.get("/health", tags=["系统"])
async def health_check(request: Request) -> Response:
    """返回服务基础健康状态。"""

    return success_response(
        data={"status": "ok", "environment": settings.app_env},
        request_id=request.state.request_id,
    )
