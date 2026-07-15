from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses import success_response
from app.database import get_db_session
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import LoginRequest, TokenResponse
from app.modules.auth.security import create_access_token, get_access_token_expire_seconds
from app.modules.users.models import User
from app.modules.users.schemas import UserResponse
from app.modules.users.service import authenticate_user

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    """校验用户名和密码后返回访问令牌。"""

    user = await authenticate_user(session, payload.username, payload.password)
    token = create_access_token(user)
    return success_response(
        data=TokenResponse(access_token=token, expires_in=get_access_token_expire_seconds()).model_dump(),
        request_id=request.state.request_id,
    )


@router.get("/me")
async def get_current_user_info(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    """返回当前登录用户。"""

    return success_response(data=UserResponse.model_validate(current_user).model_dump(), request_id=request.state.request_id)
