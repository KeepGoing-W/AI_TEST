from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import AppError
from app.database import get_db_session
from app.modules.auth.dependencies import get_current_user, require_admin
from app.modules.projects.models import Project
from app.modules.projects.repository import ProjectRepository
from app.modules.users.models import User, UserRole


async def require_project_access(
    project_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Project:
    """校验当前用户具备项目访问权限。"""

    project = await ProjectRepository(session).get_by_id(project_id)
    if project is None:
        raise AppError("PROJECT_NOT_FOUND", "项目不存在", 404)
    if current_user.role == UserRole.ADMIN:
        return project
    if not await ProjectRepository(session).has_member(project_id, current_user.id):
        raise AppError("PROJECT_ACCESS_DENIED", "无权访问该项目", 403)
    return project


CurrentAdmin = Annotated[User, Depends(require_admin)]
AccessibleProject = Annotated[Project, Depends(require_project_access)]
