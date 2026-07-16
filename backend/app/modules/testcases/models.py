import enum
from uuid import UUID

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TestCaseCategory(str, enum.Enum):
    """M4 支持生成的四类单接口测试场景。"""

    FUNCTIONAL = "functional"
    BOUNDARY = "boundary"
    EXCEPTION = "exception"
    PERMISSION = "permission"


class TestCaseStatus(str, enum.Enum):
    """未审核草稿不得进入 M5 执行器。"""

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    DISABLED = "disabled"


class TestCase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """可编辑、可审核且与生成证据绑定的测试用例。"""

    __tablename__ = "test_cases"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    source_scan_id: Mapped[UUID] = mapped_column(ForeignKey("source_scans.id", ondelete="RESTRICT"), nullable=False)
    api_definition_id: Mapped[UUID] = mapped_column(ForeignKey("api_definitions.id", ondelete="RESTRICT"), nullable=False)
    agent_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    category: Mapped[TestCaseCategory] = mapped_column(
        Enum(TestCaseCategory, name="test_case_category", native_enum=True), nullable=False
    )
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="P1", server_default="P1")
    status: Mapped[TestCaseStatus] = mapped_column(
        Enum(TestCaseStatus, name="test_case_status", native_enum=True), nullable=False, default=TestCaseStatus.DRAFT
    )
    preconditions: Mapped[list[object]] = mapped_column(JSONB, nullable=False, default=list)
    request_template: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    source_rule_ids: Mapped[list[object]] = mapped_column(JSONB, nullable=False, default=list)
    source_symbol_ids: Mapped[list[object]] = mapped_column(JSONB, nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(nullable=False)
    is_inferred: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class TestAssertion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """用例请求完成后由 M5 确定性执行器解释的断言草稿。"""

    __tablename__ = "test_assertions"

    test_case_id: Mapped[UUID] = mapped_column(ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    assertion_type: Mapped[str] = mapped_column(String(64), nullable=False)
    config: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
