from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses import success_response
from app.database import get_db_session
from app.modules.agents.schemas import TestCaseUpdateRequest
from app.modules.projects.dependencies import AccessibleProject
from app.modules.testcases.service import list_test_cases, update_test_case

router = APIRouter(prefix="/projects/{project_id}/testcases", tags=["测试用例"])


@router.get("")
async def get_test_cases(
    project: AccessibleProject,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    agent_run_id: Annotated[UUID | None, Query()] = None,
    api_definition_id: Annotated[UUID | None, Query()] = None,
) -> object:
    """查询当前项目的 Agent 草稿与已审核用例。"""

    items = await list_test_cases(session, project.id, agent_run_id, api_definition_id)
    return success_response(
        data=[item.model_dump(mode="json") for item in items], request_id=request.state.request_id
    )


@router.patch("/{case_id}")
async def patch_test_case(
    project: AccessibleProject,
    case_id: UUID,
    payload: TestCaseUpdateRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> object:
    """审核前编辑请求模板与断言草稿。"""

    item = await update_test_case(session, project.id, case_id, payload)
    return success_response(data=item.model_dump(mode="json"), request_id=request.state.request_id)
