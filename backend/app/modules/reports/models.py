from uuid import UUID

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ExecutionDiagnosis(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """一次基于固定执行证据生成的失败诊断，只保存假设而不修改结果。"""

    __tablename__ = "execution_diagnoses"

    execution_run_id: Mapped[UUID] = mapped_column(ForeignKey("execution_runs.id", ondelete="CASCADE"), nullable=False)
    execution_step_id: Mapped[UUID | None] = mapped_column(ForeignKey("execution_steps.id", ondelete="SET NULL"), nullable=True)
    failure_category: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_summary: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    source_references: Mapped[list[object]] = mapped_column(JSONB, nullable=False, default=list)
    hypotheses: Mapped[list[object]] = mapped_column(JSONB, nullable=False, default=list)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
