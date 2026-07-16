import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TaskType(str, enum.Enum):
    """后台任务类型。"""

    SOURCE_SCAN = "source_scan"
    KNOWLEDGE_EMBEDDING = "knowledge_embedding"
    EXECUTION = "execution"


class TaskStatus(str, enum.Enum):
    """后台任务状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScanStatus(str, enum.Enum):
    """源码扫描状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SymbolType(str, enum.Enum):
    """源码符号类型。"""

    CLASS = "class"
    INTERFACE = "interface"
    ENUM = "enum"
    METHOD = "method"
    FIELD = "field"
    DTO = "dto"
    EXCEPTION = "exception"
    REPOSITORY = "repository"
    MAPPER = "mapper"


class RelationType(str, enum.Enum):
    """代码符号关系类型。"""

    CALLS = "calls"
    REFERENCES = "references"
    THROWS = "throws"
    USES_DTO = "uses_dto"


class BackgroundTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """由 PostgreSQL 队列驱动的后台任务。"""

    __tablename__ = "background_tasks"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    task_type: Mapped[TaskType] = mapped_column(Enum(TaskType, name="task_type", native_enum=True), nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status", native_enum=True), nullable=False, default=TaskStatus.PENDING
    )
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SourceScan(UUIDPrimaryKeyMixin, Base):
    """一次独立的源码扫描版本。"""

    __tablename__ = "source_scans"
    __table_args__ = (UniqueConstraint("project_id", "scan_version", name="uq_source_scans_project_version"),)

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    source_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_artifacts.id", ondelete="SET NULL"), nullable=True
    )
    background_task_id: Mapped[UUID] = mapped_column(
        ForeignKey("background_tasks.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    scan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ScanStatus] = mapped_column(
        Enum(ScanStatus, name="scan_status", native_enum=True), nullable=False, default=ScanStatus.PENDING
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SourceFile(UUIDPrimaryKeyMixin, Base):
    """扫描版本中的受控 Java 源文件快照。"""

    __tablename__ = "source_files"
    __table_args__ = (UniqueConstraint("source_scan_id", "relative_path", name="uq_source_files_scan_path"),)

    source_scan_id: Mapped[UUID] = mapped_column(ForeignKey("source_scans.id", ondelete="CASCADE"), nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(32), nullable=False, default="java", server_default="java")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_ignored: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CodeSymbol(UUIDPrimaryKeyMixin, Base):
    """扫描版本中的代码符号。"""

    __tablename__ = "code_symbols"
    __table_args__ = (UniqueConstraint("source_scan_id", "qualified_name", name="uq_code_symbols_scan_qualified_name"),)

    source_scan_id: Mapped[UUID] = mapped_column(ForeignKey("source_scans.id", ondelete="CASCADE"), nullable=False)
    source_file_id: Mapped[UUID] = mapped_column(ForeignKey("source_files.id", ondelete="CASCADE"), nullable=False)
    parent_symbol_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("code_symbols.id", ondelete="SET NULL"), nullable=True
    )
    symbol_type: Mapped[SymbolType] = mapped_column(
        Enum(SymbolType, name="symbol_type", native_enum=True), nullable=False
    )
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    qualified_name: Mapped[str] = mapped_column(Text, nullable=False)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    annotations: Mapped[list[object]] = mapped_column(JSONB, nullable=False, default=list)
    metadata_: Mapped[dict[str, object]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ApiDefinition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """由源码路由扫描产生的接口定义。"""

    __tablename__ = "api_definitions"
    __table_args__ = (
        UniqueConstraint("source_scan_id", "method", "normalized_path", name="uq_api_definitions_scan_route"),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    source_scan_id: Mapped[UUID] = mapped_column(ForeignKey("source_scans.id", ondelete="CASCADE"), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    normalized_path: Mapped[str] = mapped_column(Text, nullable=False)
    operation_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    controller_symbol_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("code_symbols.id", ondelete="SET NULL"), nullable=True
    )
    method_symbol_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("code_symbols.id", ondelete="SET NULL"), nullable=True
    )
    request_definition: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    response_definition: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    security_definition: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    source_definition: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    openapi_definition: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    conflicts: Mapped[list[object]] = mapped_column(JSONB, nullable=False, default=list)
    is_conflicted: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")


class SymbolRelation(UUIDPrimaryKeyMixin, Base):
    """同一扫描版本中代码符号间的有向关系。"""

    __tablename__ = "symbol_relations"
    __table_args__ = (
        UniqueConstraint("source_symbol_id", "target_symbol_id", "relation_type", name="uq_symbol_relations_unique"),
    )

    source_scan_id: Mapped[UUID] = mapped_column(ForeignKey("source_scans.id", ondelete="CASCADE"), nullable=False)
    source_symbol_id: Mapped[UUID] = mapped_column(ForeignKey("code_symbols.id", ondelete="CASCADE"), nullable=False)
    target_symbol_id: Mapped[UUID] = mapped_column(ForeignKey("code_symbols.id", ondelete="CASCADE"), nullable=False)
    relation_type: Mapped[RelationType] = mapped_column(
        Enum(RelationType, name="relation_type", native_enum=True), nullable=False
    )
    metadata_: Mapped[dict[str, object]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
