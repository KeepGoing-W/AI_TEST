from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses import success_response
from app.database import get_db_session
from app.modules.auth.dependencies import get_current_user
from app.modules.knowledge.hybrid_retrieval import retrieve_hybrid_context
from app.modules.knowledge.schemas import EmbeddingRetryResponse, KnowledgeContextResponse
from app.modules.knowledge.service import retry_embeddings
from app.modules.projects.dependencies import AccessibleProject
from app.modules.users.models import User

router = APIRouter(prefix="/projects/{project_id}/source-scans/{scan_id}", tags=["项目知识库"])


@router.get("/api-definitions/{api_definition_id}/context")
async def get_api_knowledge_context(
    project: AccessibleProject,
    scan_id: UUID,
    api_definition_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    query: Annotated[str | None, Query(max_length=500)] = None,
    max_results: Annotated[int | None, Query(ge=1, le=50)] = None,
) -> object:
    # AccessibleProject 已在依赖层完成项目成员校验，Service 仅处理检索语义。
    context = await retrieve_hybrid_context(
        session,
        project.id,
        scan_id,
        api_definition_id,
        query,
        max_results,
    )
    return success_response(
        data=KnowledgeContextResponse.model_validate(context).model_dump(mode="json"),
        request_id=request.state.request_id,
    )


@router.post("/knowledge/embedding-retries")
async def retry_knowledge_embeddings(
    project: AccessibleProject,
    scan_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> object:
    # 重试任务仍使用当前用户身份记录 requested_by，方便后续追溯。
    task_id = await retry_embeddings(session, project.id, scan_id, current_user.id)
    return success_response(
        data=EmbeddingRetryResponse(task_id=task_id, source_scan_id=scan_id).model_dump(mode="json"),
        request_id=request.state.request_id,
        status_code=201,
    )
