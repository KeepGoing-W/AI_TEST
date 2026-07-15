import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import AppError
from app.config import get_settings
from app.modules.auth.security import hash_password, verify_password
from app.modules.users.models import User, UserRole
from app.modules.users.repository import UserRepository
from app.modules.users.schemas import CreateUserRequest

logger = logging.getLogger(__name__)


async def authenticate_user(session: AsyncSession, username: str, password: str) -> User:
    """校验用户凭据和启用状态。"""

    user = await UserRepository(session).get_by_username(username)
    if user is None or not verify_password(password, user.password_hash):
        raise AppError("AUTH_INVALID_CREDENTIALS", "用户名或密码错误", 401)
    if not user.is_active:
        raise AppError("AUTH_USER_DISABLED", "用户已被禁用", 403)
    return user


async def create_user(session: AsyncSession, payload: CreateUserRequest) -> User:
    """创建平台用户。"""

    repository = UserRepository(session)
    if await repository.get_by_username(payload.username) is not None:
        raise AppError("USER_USERNAME_EXISTS", "用户名已存在", 409)

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        role=payload.role,
    )
    repository.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def update_user_status(session: AsyncSession, user_id: UUID, is_active: bool) -> User:
    """更新用户启用状态。"""

    user = await UserRepository(session).get_by_id(user_id)
    if user is None:
        raise AppError("USER_NOT_FOUND", "用户不存在", 404)
    user.is_active = is_active
    await session.commit()
    await session.refresh(user)
    return user


async def initialize_admin_user(session: AsyncSession) -> None:
    """按环境变量创建首个管理员，已存在时不覆盖。"""

    settings = get_settings()
    if settings.initial_admin_username is None or settings.initial_admin_password is None:
        logger.warning("未配置初始化管理员，跳过创建")
        return

    repository = UserRepository(session)
    if await repository.get_by_username(settings.initial_admin_username) is not None:
        return

    user = User(
        username=settings.initial_admin_username,
        password_hash=hash_password(settings.initial_admin_password.get_secret_value()),
        display_name=settings.initial_admin_display_name,
        role=UserRole.ADMIN,
    )
    repository.add(user)
    await session.commit()
    logger.info("初始化管理员已创建，username=%s", user.username)
