from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses import success_response
from app.database import get_db_session
from app.modules.auth.dependencies import get_current_user
from app.modules.projects.dependencies import AccessibleProject, CurrentAdmin
from app.modules.projects.models import Project
from app.modules.projects.repository import ProjectRepository
from app.modules.projects.schemas import (
    AddProjectMemberRequest,
    CreateProjectRequest,
    ProjectMemberResponse,
    ProjectResponse,
    LocalSourceRequest,
    OpenApiSourceResponse,
    OpenApiUrlRequest,
    SourceArtifactResponse,
    UpdateProjectRequest,
)
from app.modules.projects.service import add_project_member, configure_local_source, configure_zip_source, create_project, delete_project, remove_project_member, update_project
from app.modules.projects.service import configure_openapi_file, configure_openapi_url
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/projects", tags=["项目管理"])


@router.get("/{project_id}/openapi")
async def get_openapi_source(project: AccessibleProject, request: Request) -> Response:
    return success_response(data=OpenApiSourceResponse(source_type=project.openapi_source_type, configured=project.openapi_location is not None).model_dump(), request_id=request.state.request_id)


@router.put("/{project_id}/openapi/url")
async def set_openapi_url(project: AccessibleProject, payload: OpenApiUrlRequest, request: Request, session: Annotated[AsyncSession, Depends(get_db_session)], _: CurrentAdmin) -> Response:
    updated = await configure_openapi_url(session, project, payload.url)
    return success_response(data=OpenApiSourceResponse(source_type=updated.openapi_source_type, configured=True).model_dump(), request_id=request.state.request_id)


@router.put("/{project_id}/openapi/file")
async def set_openapi_file(
    project: AccessibleProject,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: CurrentAdmin,
    file: UploadFile = File(...),
) -> Response:
    updated = await configure_openapi_file(session, project, await file.read(), file.filename or "openapi.yaml")
    return success_response(
        data=OpenApiSourceResponse(source_type=updated.openapi_source_type, configured=True).model_dump(),
        request_id=request.state.request_id,
    )


@router.get("/{project_id}/source")
async def get_project_source(project: AccessibleProject, request: Request, session: Annotated[AsyncSession, Depends(get_db_session)]) -> Response:
    artifact = await ProjectRepository(session).get_source_artifact(project.id)
    return success_response(data=None if artifact is None else SourceArtifactResponse.model_validate(artifact).model_dump(), request_id=request.state.request_id)


@router.put("/{project_id}/source/local")
async def set_local_project_source(project: AccessibleProject, payload: LocalSourceRequest, request: Request, session: Annotated[AsyncSession, Depends(get_db_session)], current_user: CurrentAdmin) -> Response:
    artifact = await configure_local_source(session, project.id, payload.path, current_user.id)
    return success_response(data=SourceArtifactResponse.model_validate(artifact).model_dump(), request_id=request.state.request_id)


@router.put("/{project_id}/source/zip")
async def set_zip_project_source(project: AccessibleProject, request: Request, session: Annotated[AsyncSession, Depends(get_db_session)], current_user: CurrentAdmin, file: UploadFile = File(...)) -> Response:
    artifact = await configure_zip_source(session, project.id, await file.read(), file.filename or "source.zip", current_user.id)
    return success_response(data=SourceArtifactResponse.model_validate(artifact).model_dump(), request_id=request.state.request_id)


@router.get("")
async def list_projects(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    """查询当前用户可访问的项目。"""

    repository = ProjectRepository(session)
    projects = await (
        repository.list_all() if current_user.role == UserRole.ADMIN else repository.list_by_user_id(current_user.id)
    )
    return success_response(
        data=[ProjectResponse.model_validate(project).model_dump() for project in projects],
        request_id=request.state.request_id,
    )


@router.post("")
async def create_project_item(
    payload: CreateProjectRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: CurrentAdmin,
) -> Response:
    """由管理员创建项目。"""

    project = await create_project(session, payload, current_user.id)
    return success_response(
        data=ProjectResponse.model_validate(project).model_dump(),
        request_id=request.state.request_id,
        status_code=201,
    )


@router.get("/{project_id}")
async def get_project(project: AccessibleProject, request: Request) -> Response:
    """获取单个项目。"""

    return success_response(data=ProjectResponse.model_validate(project).model_dump(), request_id=request.state.request_id)


@router.patch("/{project_id}")
async def update_project_item(
    payload: UpdateProjectRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: CurrentAdmin,
    project: AccessibleProject,
) -> Response:
    """由管理员更新项目。"""

    updated_project = await update_project(session, project, payload)
    return success_response(
        data=ProjectResponse.model_validate(updated_project).model_dump(),
        request_id=request.state.request_id,
    )


@router.delete("/{project_id}")
async def delete_project_item(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: CurrentAdmin,
    project: AccessibleProject,
) -> Response:
    """由管理员删除项目。"""

    await delete_project(session, project)
    return success_response(data=None, request_id=request.state.request_id)


@router.get("/{project_id}/members")
async def list_project_members(
    project: AccessibleProject,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    """查询项目成员。"""

    members = await ProjectRepository(session).list_members(project.id)
    return success_response(
        data=[ProjectMemberResponse.model_validate(member).model_dump() for member in members],
        request_id=request.state.request_id,
    )


@router.post("/{project_id}/members")
async def add_project_member_item(
    project: AccessibleProject,
    payload: AddProjectMemberRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: CurrentAdmin,
) -> Response:
    """由管理员添加项目成员。"""

    member = await add_project_member(session, project.id, payload.user_id)
    return success_response(
        data=ProjectMemberResponse.model_validate(member).model_dump(),
        request_id=request.state.request_id,
        status_code=201,
    )


@router.delete("/{project_id}/members/{user_id}")
async def remove_project_member_item(
    project: AccessibleProject,
    user_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: CurrentAdmin,
) -> Response:
    """由管理员移除项目成员。"""

    await remove_project_member(session, project.id, user_id)
    return success_response(data=None, request_id=request.state.request_id)
