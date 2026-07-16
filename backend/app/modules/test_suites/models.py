import enum
from uuid import UUID

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class VariableExtractionSource(str, enum.Enum):
    """流程步骤可受控读取的响应位置。"""

    JSON_PATH = "json_path"
    RESPONSE_HEADER = "response_header"
    TEXT = "text"
    STATUS_CODE = "status_code"


class TestSuite(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """由已审核用例组成的顺序回归流程。"""

    __tablename__ = "test_suites"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    stop_on_failure: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class TestSuiteStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """流程中的一个固定位置；覆盖内容只在此次流程请求中生效。"""

    __tablename__ = "test_suite_steps"
    __table_args__ = (UniqueConstraint("test_suite_id", "position", name="uq_test_suite_steps_position"),)

    test_suite_id: Mapped[UUID] = mapped_column(ForeignKey("test_suites.id", ondelete="CASCADE"), nullable=False)
    test_case_id: Mapped[UUID] = mapped_column(ForeignKey("test_cases.id", ondelete="RESTRICT"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    request_override: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)


class VariableExtraction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """上游响应到本次运行变量空间的显式映射。"""

    __tablename__ = "variable_extractions"
    __table_args__ = (
        UniqueConstraint("test_suite_step_id", "variable_key", name="uq_variable_extractions_step_key"),
    )

    test_suite_step_id: Mapped[UUID] = mapped_column(ForeignKey("test_suite_steps.id", ondelete="CASCADE"), nullable=False)
    variable_key: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[VariableExtractionSource] = mapped_column(
        Enum(VariableExtractionSource, name="variable_extraction_source", native_enum=True), nullable=False
    )
    expression: Mapped[str | None] = mapped_column(Text, nullable=True)
