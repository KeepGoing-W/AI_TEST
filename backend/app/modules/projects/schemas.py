from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.projects.models import OpenApiSourceType, SourceType


class CreateProjectRequest(BaseModel):
    """创建项目请求。"""

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=10_000)


class UpdateProjectRequest(BaseModel):
    """更新项目基础信息请求。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=10_000)


class AddProjectMemberRequest(BaseModel):
    """添加项目成员请求。"""

    user_id: UUID


class ProjectResponse(BaseModel):
    """项目响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str
    language: str
    framework: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class ProjectMemberResponse(BaseModel):
    """项目成员响应。"""

    model_config = ConfigDict(from_attributes=True)

    project_id: UUID
    user_id: UUID
    created_at: datetime


class LocalSourceRequest(BaseModel):
    """本地源码目录配置。"""

    path: str = Field(min_length=1, max_length=4096)


class SourceArtifactResponse(BaseModel):
    """源码来源响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_type: SourceType
    original_name: str | None
    size_bytes: int | None
    created_at: datetime


class OpenApiUrlRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class OpenApiSourceResponse(BaseModel):
    source_type: OpenApiSourceType | None
    configured: bool
