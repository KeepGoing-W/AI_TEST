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
from app.modules.projects.dependencies import AccessibleProject
from app.modules.source_scans.models import BackgroundTask
from app.modules.source_scans.repository import SourceScanRepository
from app.modules.source_scans.schemas import ScanProgressEvent, SourceScanResponse
from app.modules.source_scans.service import create_source_scan, get_source_scan_api_definition, list_source_scan_api_definitions
from app.modules.users.models import User

router = APIRouter(prefix="/projects/{project_id}/source-scans", tags=["源码扫描"])


@router.post("")
async def start_source_scan(
    project: AccessibleProject,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> object:
    scan = await create_source_scan(session, project.id, current_user.id)
    return success_response(
        data=SourceScanResponse.model_validate(scan).model_dump(),
        request_id=request.state.request_id,
        status_code=201,
    )


@router.get("")
async def list_source_scans(
    project: AccessibleProject,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> object:
    scans = await SourceScanRepository(session).list_scans(project.id)
    return success_response(
        data=[SourceScanResponse.model_validate(scan).model_dump() for scan in scans],
        request_id=request.state.request_id,
    )


@router.get("/{scan_id}")
async def get_source_scan(
    project: AccessibleProject,
    scan_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> object:
    scan = await SourceScanRepository(session).get_scan(project.id, scan_id)
    if scan is None:
        raise AppError("SOURCE_SCAN_NOT_FOUND", "扫描任务不存在", 404)
    return success_response(data=SourceScanResponse.model_validate(scan).model_dump(), request_id=request.state.request_id)


@router.get("/{scan_id}/api-definitions")
async def list_api_definitions(
    project: AccessibleProject,
    scan_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> object:
    payload = await list_source_scan_api_definitions(session, project.id, scan_id)
    return success_response(data=payload, request_id=request.state.request_id)


@router.get("/{scan_id}/api-definitions/{api_definition_id}")
async def get_api_definition(
    project: AccessibleProject,
    scan_id: UUID,
    api_definition_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> object:
    payload = await get_source_scan_api_definition(session, project.id, scan_id, api_definition_id)
    return success_response(
        data=payload, request_id=request.state.request_id
    )


@router.get("/{scan_id}/events")
async def stream_source_scan_progress(
    project: AccessibleProject,
    scan_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StreamingResponse:
    scan = await SourceScanRepository(session).get_scan(project.id, scan_id)
    if scan is None:
        raise AppError("SOURCE_SCAN_NOT_FOUND", "扫描任务不存在", 404)
    await session.rollback()

    async def event_stream() -> AsyncIterator[str]:
        last_event: str | None = None
        while True:
            async with session.begin():
                current = await SourceScanRepository(session).get_scan(project.id, scan_id)
                if current is None:
                    return
                task = await session.get(BackgroundTask, current.background_task_id)
                if task is None:
                    return
                payload = ScanProgressEvent(
                    task_id=task.id,
                    scan_id=current.id,
                    scan_version=current.scan_version,
                    task_status=task.status,
                    scan_status=current.status,
                    progress=int(task.result.get("progress", 0)),
                    phase=str(task.result.get("phase", "pending")),
                    error_code=current.error_code,
                ).model_dump(mode="json")
            serialized = json.dumps(payload, ensure_ascii=False)
            if serialized != last_event:
                yield f"event: progress\ndata: {serialized}\n\n"
                last_event = serialized
            if payload["scan_status"] in {"succeeded", "failed", "cancelled"}:
                return
            await asyncio.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
