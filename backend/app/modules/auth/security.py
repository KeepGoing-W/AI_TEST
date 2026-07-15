from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash

from app.common.errors import AppError
from app.config import get_settings
from app.modules.users.models import User, UserRole

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """使用 Argon2 散列密码。"""

    return password_hash.hash(password)


def verify_password(password: str, password_hash_value: str) -> bool:
    """校验密码与 Argon2 散列值。"""

    return password_hash.verify(password, password_hash_value)


def create_access_token(user: User) -> str:
    """为已启用用户签发访问令牌。"""

    settings = get_settings()
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "iat": issued_at,
        "exp": expires_at,
        "iss": settings.jwt_issuer,
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")


def get_access_token_expire_seconds() -> int:
    """返回访问令牌有效期秒数。"""

    return get_settings().jwt_access_token_expire_minutes * 60


def get_user_id_from_access_token(token: str) -> UUID:
    """校验访问令牌并返回用户标识。"""

    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
        )
        return UUID(str(payload["sub"]))
    except (InvalidTokenError, KeyError, ValueError) as exc:
        raise AppError("AUTH_TOKEN_INVALID", "登录状态无效或已过期", 401) from exc
