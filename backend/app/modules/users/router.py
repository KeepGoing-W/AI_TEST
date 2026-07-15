from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses import success_response
from app.database import get_db_session
from app.modules.auth.dependencies import require_admin
from app.modules.users.models import User
from app.modules.users.schemas import CreateUserRequest, UpdateUserStatusRequest, UserResponse
from app.modules.users.service import create_user, update_user_status

router = APIRouter(prefix="/users", tags=["用户管理"])


@router.post("")
async def create_platform_user(
    payload: CreateUserRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[User, Depends(require_admin)],
) -> Response:
    """由管理员创建用户。"""

    user = await create_user(session, payload)
    return success_response(
        data=UserResponse.model_validate(user).model_dump(),
        request_id=request.state.request_id,
        status_code=201,
    )


@router.patch("/{user_id}/status")
async def change_platform_user_status(
    user_id: UUID,
    payload: UpdateUserStatusRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[User, Depends(require_admin)],
) -> Response:
    """由管理员启用或禁用用户。"""

    user = await update_user_status(session, user_id, payload.is_active)
    return success_response(data=UserResponse.model_validate(user).model_dump(), request_id=request.state.request_id)
