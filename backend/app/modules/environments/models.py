import enum
from uuid import UUID

from sqlalchemy import Boolean, Enum, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EnvironmentType(str, enum.Enum):
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class TestEnvironment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "test_environments"
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    environment_type: Mapped[EnvironmentType] = mapped_column(Enum(EnvironmentType, name="environment_type", native_enum=True), nullable=False)
    allow_write_requests: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    common_headers: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    host_allowlist: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class EnvironmentVariable(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "environment_variables"
    environment_id: Mapped[UUID] = mapped_column(ForeignKey("test_environments.id", ondelete="CASCADE"), nullable=False)
    variable_key: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_secret: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
