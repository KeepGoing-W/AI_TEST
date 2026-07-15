import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SourceType(str, enum.Enum):
    """项目源码来源类型。"""

    LOCAL_PATH = "local_path"
    ZIP_UPLOAD = "zip_upload"


class OpenApiSourceType(str, enum.Enum):
    """OpenAPI 来源类型。"""

    URL = "url"
    FILE = "file"


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """被测项目。"""

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("language = 'java'", name="ck_projects_language"),
        CheckConstraint("framework = 'spring_boot'", name="ck_projects_framework"),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    language: Mapped[str] = mapped_column(String(32), nullable=False, default="java", server_default="java")
    framework: Mapped[str] = mapped_column(String(32), nullable=False, default="spring_boot", server_default="spring_boot")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    openapi_source_type: Mapped[OpenApiSourceType | None] = mapped_column(
        Enum(OpenApiSourceType, name="openapi_source_type", native_enum=True), nullable=True
    )
    openapi_location: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProjectMember(Base):
    """项目与测试成员的访问授权。"""

    __tablename__ = "project_members"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SourceArtifact(UUIDPrimaryKeyMixin, Base):
    """项目登记的源码包。"""

    __tablename__ = "source_artifacts"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType, name="source_type", native_enum=True), nullable=False)
    storage_location: Mapped[str] = mapped_column(Text, nullable=False)
    original_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
