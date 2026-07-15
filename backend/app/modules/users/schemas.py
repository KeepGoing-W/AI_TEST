from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.users.models import UserRole


class UserResponse(BaseModel):
    """用户响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    display_name: str
    role: UserRole
    is_active: bool


class CreateUserRequest(BaseModel):
    """管理员创建用户请求。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    role: UserRole = UserRole.TEST_MEMBER


class UpdateUserStatusRequest(BaseModel):
    """管理员更新用户状态请求。"""

    is_active: bool
