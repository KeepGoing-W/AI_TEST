import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import AppError
from app.common.responses import success_response
from app.database import get_db_session
from app.modules.auth.dependencies import get_current_user
from app.modules.executions.models import ExecutionRunStatus, ExecutionStepStatus
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.schemas import ExecutionProgressEvent, ExecutionRetryRequest, ExecutionStartRequest
from app.modules.executions.service import (
    create_execution_run,
    get_execution_response,
    request_execution_stop,
    retry_failed_execution,
)
from app.modules.projects.dependencies import AccessibleProject
from app.modules.users.models import User

router = APIRouter(prefix="/projects/{project_id}/executions", tags=["测试执行"])


@router.post("")
async def start_execution(
    project: AccessibleProject,
    payload: ExecutionStartRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> object:
    """创建单用例或批量执行任务。"""

    run = await create_execution_run(session, project.id, current_user, payload)
    return success_response(data=(await get_execution_response(session, project.id, run.id)).model_dump(mode="json"), request_id=request.state.request_id, status_code=201)


@router.get("")
async def list_executions(
    project: AccessibleProject,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> object:
    """返回执行摘要，详情按需单独查询。"""

    runs = await ExecutionRepository(session).list_runs(project.id)
    return success_response(
        data=[(await get_execution_response(session, project.id, run.id)).model_dump(mode="json", exclude={"steps"}) for run in runs],
        request_id=request.state.request_id,
    )


@router.get("/{run_id}")
async def get_execution(
    project: AccessibleProject,
    run_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> object:
    return success_response(
        data=(await get_execution_response(session, project.id, run_id)).model_dump(mode="json"),
        request_id=request.state.request_id,
    )


@router.post("/{run_id}/stop")
async def stop_execution(
    project: AccessibleProject,
    run_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> object:
    """请求停止后台任务，不中断已经发出的 HTTP 请求。"""

    run = await request_execution_stop(session, project.id, run_id)
    return success_response(data=(await get_execution_response(session, project.id, run.id)).model_dump(mode="json"), request_id=request.state.request_id)


@router.post("/{run_id}/retry")
async def retry_execution(
    project: AccessibleProject,
    run_id: UUID,
    payload: ExecutionRetryRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> object:
    """重新提交失败或异常的用例。"""

    run = await retry_failed_execution(
        session, project.id, current_user, run_id, payload.write_confirmed, payload.confirmed_host
    )
    return success_response(data=(await get_execution_response(session, project.id, run.id)).model_dump(mode="json"), request_id=request.state.request_id, status_code=201)


@router.get("/{run_id}/events")
async def stream_execution_progress(
    project: AccessibleProject,
    run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StreamingResponse:
    """轮询持久化执行记录，向前端推送脱敏进度。"""

    if await ExecutionRepository(session).get_run(project.id, run_id) is None:
        raise AppError("EXECUTION_RUN_NOT_FOUND", "执行任务不存在", 404)
    await session.rollback()

    async def event_stream() -> AsyncIterator[str]:
        last_event: str | None = None
        while True:
            async with session.begin():
                run = await ExecutionRepository(session).get_run(project.id, run_id)
                if run is None:
                    return
                steps = await ExecutionRepository(session).list_steps(run.id)
                current = next((step for step in steps if step.status == ExecutionStepStatus.RUNNING), None)
                payload = ExecutionProgressEvent(
                    run_id=run.id,
                    status=run.status,
                    total_count=run.total_count,
                    passed_count=run.passed_count,
                    failed_count=run.failed_count,
                    skipped_count=run.skipped_count,
                    current_step_id=current.id if current is not None else None,
                ).model_dump(mode="json")
            serialized = json.dumps(payload, ensure_ascii=False)
            if serialized != last_event:
                yield f"event: progress\ndata: {serialized}\n\n"
                last_event = serialized
            if payload["status"] in {ExecutionRunStatus.COMPLETED, ExecutionRunStatus.FAILED, ExecutionRunStatus.STOPPED}:
                return
            await asyncio.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
