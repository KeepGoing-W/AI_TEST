import enum
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AgentRunStatus(str, enum.Enum):
    """Agent 运行从创建到人工审核结束的稳定状态。"""

    PENDING = "pending"
    RUNNING = "running"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    DISABLED = "disabled"
    FAILED = "failed"


class AgentErrorCategory(str, enum.Enum):
    """便于前端和恢复逻辑稳定处理的 Agent 错误分类。"""

    INPUT = "input"
    RETRIEVAL = "retrieval"
    MODEL = "model"
    OUTPUT = "output"
    INTERRUPT = "interrupt"
    RECOVERY = "recovery"


class AgentRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """一次面向固定项目、扫描版本和接口集合的 Agent 运行。"""

    __tablename__ = "agent_runs"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    source_scan_id: Mapped[UUID] = mapped_column(ForeignKey("source_scans.id", ondelete="RESTRICT"), nullable=False)
    llm_config_id: Mapped[UUID | None] = mapped_column(ForeignKey("llm_configs.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # 接口集合使用 JSONB 保存，避免为了单次 Agent 运行引入无复用价值的中间表。
    api_definition_ids: Mapped[list[object]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(AgentRunStatus, name="agent_run_status", native_enum=True), nullable=False, default=AgentRunStatus.PENDING
    )
    current_node: Mapped[str] = mapped_column(String(128), nullable=False, default="validate_input")
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    # 保存当次真实使用的模型名与推理参数，不能在后续配置变更时被覆盖。
    model_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    # 只保留结构化摘要、ID 与来源引用，绝不把无限增长的完整消息历史放入运行状态。
    state_summary: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    error_category: Mapped[AgentErrorCategory | None] = mapped_column(
        Enum(AgentErrorCategory, name="agent_error_category", native_enum=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentCheckpoint(UUIDPrimaryKeyMixin, Base):
    """Agent 每个可恢复节点后的结构化状态快照。"""

    __tablename__ = "agent_checkpoints"

    agent_run_id: Mapped[UUID] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    node_name: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
