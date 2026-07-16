import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ExecutionRunStatus(str, enum.Enum):
    """执行任务的生命周期状态。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class ExecutionStepStatus(str, enum.Enum):
    """单用例在一次执行中的最终状态。"""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"
    STOPPED = "stopped"


class ExecutionErrorCategory(str, enum.Enum):
    """可稳定展示和聚合的执行错误分类。"""

    REQUEST_BUILD = "request_build"
    SECURITY = "security"
    DNS = "dns"
    CONNECTION = "connection"
    TLS = "tls"
    TIMEOUT = "timeout"
    RESPONSE_TOO_LARGE = "response_too_large"
    ASSERTION = "assertion"
    INTERNAL = "internal"


class ExecutionRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """一次单用例或批量执行的不可变入口记录。"""

    __tablename__ = "execution_runs"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    environment_id: Mapped[UUID] = mapped_column(ForeignKey("test_environments.id", ondelete="RESTRICT"), nullable=False)
    background_task_id: Mapped[UUID] = mapped_column(
        ForeignKey("background_tasks.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    requested_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[ExecutionRunStatus] = mapped_column(
        Enum(ExecutionRunStatus, name="execution_run_status", native_enum=True),
        nullable=False,
        default=ExecutionRunStatus.PENDING,
    )
    stop_on_failure: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    runtime_variables: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    passed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExecutionStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """一次执行中的单用例请求、响应和结果快照。"""

    __tablename__ = "execution_steps"

    execution_run_id: Mapped[UUID] = mapped_column(ForeignKey("execution_runs.id", ondelete="CASCADE"), nullable=False)
    test_case_id: Mapped[UUID] = mapped_column(ForeignKey("test_cases.id", ondelete="RESTRICT"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ExecutionStepStatus] = mapped_column(
        Enum(ExecutionStepStatus, name="execution_step_status", native_enum=True),
        nullable=False,
        default=ExecutionStepStatus.PENDING,
    )
    method: Mapped[str | None] = mapped_column(String(10), nullable=True)
    target_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    response_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    redacted_curl: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_category: Mapped[ExecutionErrorCategory | None] = mapped_column(
        Enum(ExecutionErrorCategory, name="execution_error_category", native_enum=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    skip_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AssertionResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """断言引擎输出的确定性判定证据。"""

    __tablename__ = "assertion_results"

    execution_step_id: Mapped[UUID] = mapped_column(ForeignKey("execution_steps.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    assertion_type: Mapped[str] = mapped_column(String(64), nullable=False)
    path: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected: Mapped[object | None] = mapped_column(JSONB, nullable=True)
    actual: Mapped[object | None] = mapped_column(JSONB, nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
