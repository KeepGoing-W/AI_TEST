from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses import success_response
from app.database import get_db_session
from app.modules.auth.dependencies import get_current_user
from app.modules.executions.schemas import ExecutionRetryRequest
from app.modules.executions.service import get_execution_response
from app.modules.projects.dependencies import AccessibleProject
from app.modules.reports.service import create_failure_diagnoses, get_report, list_report_items, retry_report_execution
from app.modules.users.models import User

router = APIRouter(prefix="/projects/{project_id}/reports", tags=["执行报告"])


@router.get("")
async def list_reports(project: AccessibleProject, request: Request, session: Annotated[AsyncSession, Depends(get_db_session)]) -> object:
    return success_response(data=[item.model_dump(mode="json") for item in await list_report_items(session, project.id)], request_id=request.state.request_id)


@router.get("/{run_id}")
async def get_execution_report(project: AccessibleProject, run_id: UUID, request: Request, session: Annotated[AsyncSession, Depends(get_db_session)]) -> object:
    return success_response(data=(await get_report(session, project.id, run_id)).model_dump(mode="json"), request_id=request.state.request_id)


@router.post("/{run_id}/retry")
async def retry_report(project: AccessibleProject, run_id: UUID, payload: ExecutionRetryRequest, request: Request, session: Annotated[AsyncSession, Depends(get_db_session)], current_user: Annotated[User, Depends(get_current_user)]) -> object:
    run = await retry_report_execution(session, project.id, run_id, current_user, payload)
    return success_response(data=(await get_execution_response(session, project.id, run.id)).model_dump(mode="json"), request_id=request.state.request_id, status_code=201)


@router.post("/{run_id}/diagnoses")
async def diagnose_failures(project: AccessibleProject, run_id: UUID, request: Request, session: Annotated[AsyncSession, Depends(get_db_session)], current_user: Annotated[User, Depends(get_current_user)]) -> object:
    return success_response(data=[item.model_dump(mode="json") for item in await create_failure_diagnoses(session, project.id, run_id, current_user)], request_id=request.state.request_id, status_code=201)
