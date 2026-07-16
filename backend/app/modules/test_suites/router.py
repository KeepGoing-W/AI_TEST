from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses import success_response
from app.database import get_db_session
from app.modules.auth.dependencies import get_current_user
from app.modules.executions.service import get_execution_response
from app.modules.projects.dependencies import AccessibleProject
from app.modules.test_suites.schemas import TestSuiteCreateRequest, TestSuiteRunRequest, TestSuiteUpdateRequest
from app.modules.test_suites.service import create_test_suite, get_test_suite_response, list_test_suite_responses, start_test_suite_run, update_test_suite
from app.modules.users.models import User

router = APIRouter(prefix="/projects/{project_id}/test-suites", tags=["测试流程"])


@router.get("")
async def list_test_suites(project: AccessibleProject, request: Request, session: Annotated[AsyncSession, Depends(get_db_session)]) -> object:
    return success_response(data=[item.model_dump(mode="json") for item in await list_test_suite_responses(session, project.id)], request_id=request.state.request_id)


@router.post("")
async def create_suite(project: AccessibleProject, payload: TestSuiteCreateRequest, request: Request, session: Annotated[AsyncSession, Depends(get_db_session)], current_user: Annotated[User, Depends(get_current_user)]) -> object:
    suite = await create_test_suite(session, project.id, current_user, payload)
    return success_response(data=(await get_test_suite_response(session, project.id, suite.id)).model_dump(mode="json"), request_id=request.state.request_id, status_code=201)


@router.get("/{suite_id}")
async def get_suite(project: AccessibleProject, suite_id: UUID, request: Request, session: Annotated[AsyncSession, Depends(get_db_session)]) -> object:
    return success_response(data=(await get_test_suite_response(session, project.id, suite_id)).model_dump(mode="json"), request_id=request.state.request_id)


@router.put("/{suite_id}")
async def update_suite(project: AccessibleProject, suite_id: UUID, payload: TestSuiteUpdateRequest, request: Request, session: Annotated[AsyncSession, Depends(get_db_session)]) -> object:
    suite = await update_test_suite(session, project.id, suite_id, payload)
    return success_response(data=(await get_test_suite_response(session, project.id, suite.id)).model_dump(mode="json"), request_id=request.state.request_id)


@router.post("/{suite_id}/runs")
async def run_suite(project: AccessibleProject, suite_id: UUID, payload: TestSuiteRunRequest, request: Request, session: Annotated[AsyncSession, Depends(get_db_session)], current_user: Annotated[User, Depends(get_current_user)]) -> object:
    run = await start_test_suite_run(session, project.id, suite_id, current_user, payload.environment_id, payload.write_confirmed, payload.confirmed_host)
    return success_response(data=(await get_execution_response(session, project.id, run.id)).model_dump(mode="json"), request_id=request.state.request_id, status_code=201)
