from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import AppError
from app.database import get_db_session
from app.modules.auth.security import get_user_id_from_access_token
from app.modules.users.models import User, UserRole
from app.modules.users.repository import UserRepository

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> User:
    """解析令牌并返回当前已启用用户。"""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError("AUTH_TOKEN_MISSING", "未提供访问令牌", 401)

    user_id = get_user_id_from_access_token(credentials.credentials)
    user = await UserRepository(session).get_by_id(user_id)
    if user is None:
        raise AppError("AUTH_TOKEN_INVALID", "登录状态无效或已过期", 401)
    if not user.is_active:
        raise AppError("AUTH_USER_DISABLED", "用户已被禁用", 403)
    return user


async def require_admin(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    """限制接口仅管理员可访问。"""

    if current_user.role != UserRole.ADMIN:
        raise AppError("AUTH_PERMISSION_DENIED", "无权执行此操作", 403)
    return current_user
