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
from app.modules.agents.repository import AgentRepository
from app.modules.agents.schemas import (
    AgentRunProgressEvent,
    AgentRunResponse,
    ReviewRequest,
    TestcaseGenerationRequest,
)
from app.modules.agents.service import create_testcase_generation_run, review_agent_run
from app.modules.auth.dependencies import get_current_user
from app.modules.projects.dependencies import AccessibleProject
from app.modules.users.models import User

router = APIRouter(prefix="/projects/{project_id}/agent-runs", tags=["Agent 分析"])


@router.post("/testcase-generation")
async def start_testcase_generation(
    project: AccessibleProject,
    payload: TestcaseGenerationRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> object:
    """创建 Agent 分析任务并同步推进到人工审核中断点。"""

    run = await create_testcase_generation_run(session, project.id, current_user, payload)
    return success_response(
        data=AgentRunResponse.model_validate(run).model_dump(mode="json"),
        request_id=request.state.request_id,
        status_code=201,
    )


@router.get("/{run_id}")
async def get_agent_run(
    project: AccessibleProject,
    run_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> object:
    """读取运行状态和精简结果摘要。"""

    run = await AgentRepository(session).get_run(project.id, run_id)
    if run is None:
        raise AppError("AGENT_RUN_NOT_FOUND", "Agent 运行不存在", 404)
    return success_response(
        data=AgentRunResponse.model_validate(run).model_dump(mode="json"), request_id=request.state.request_id
    )


@router.get("/{run_id}/events")
async def stream_agent_run_progress(
    project: AccessibleProject,
    run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StreamingResponse:
    """轮询持久化运行状态，为前端节点轨道提供 SSE 事件。"""

    if await AgentRepository(session).get_run(project.id, run_id) is None:
        raise AppError("AGENT_RUN_NOT_FOUND", "Agent 运行不存在", 404)
    await session.rollback()

    async def event_stream() -> AsyncIterator[str]:
        last_event: str | None = None
        while True:
            async with session.begin():
                run = await AgentRepository(session).get_run(project.id, run_id)
                if run is None:
                    return
                event = AgentRunProgressEvent(
                    run_id=run.id,
                    status=run.status,
                    current_node=run.current_node,
                    error_code=run.error_code,
                ).model_dump(mode="json")
            serialized = json.dumps(event, ensure_ascii=False)
            if serialized != last_event:
                yield f"event: progress\ndata: {serialized}\n\n"
                last_event = serialized
            if event["status"] in {"pending_review", "approved", "disabled", "failed"}:
                return
            await asyncio.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/{run_id}/approve")
async def approve_agent_run(
    project: AccessibleProject,
    run_id: UUID,
    payload: ReviewRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> object:
    """人工审核同一运行下的全部用例；本阶段仅审核，不触发执行。"""

    run = await review_agent_run(session, project.id, run_id, current_user, payload)
    return success_response(
        data=AgentRunResponse.model_validate(run).model_dump(mode="json"), request_id=request.state.request_id
    )
