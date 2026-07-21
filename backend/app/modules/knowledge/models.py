import enum
from uuid import UUID

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.common.models import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_values


class KnowledgeChunkType(str, enum.Enum):
    """知识切块的源码语义类型。"""

    CLASS = "class"
    METHOD = "method"
    DTO = "dto"
    SQL = "sql"
    EXCEPTION = "exception"


class BusinessRuleSourceType(str, enum.Enum):
    """业务规则的证据来源类型。"""

    SOURCE_CONFIRMED = "source_confirmed"
    INFERRED = "inferred"


class EmbeddingStatus(str, enum.Enum):
    """知识切块的向量生成状态。"""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class KnowledgeChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """与扫描版本绑定的、按源码语义划分的检索单元。"""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint(
            "source_scan_id", "source_file_id", "chunk_type", "start_line", "end_line", "code_symbol_id",
            name="uq_knowledge_chunks_scan_source_range",
        ),
        CheckConstraint("start_line > 0 AND end_line >= start_line", name="ck_knowledge_chunks_line_range"),
    )

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    source_scan_id: Mapped[UUID] = mapped_column(ForeignKey("source_scans.id", ondelete="CASCADE"), nullable=False)
    source_file_id: Mapped[UUID] = mapped_column(ForeignKey("source_files.id", ondelete="CASCADE"), nullable=False)
    code_symbol_id: Mapped[UUID | None] = mapped_column(ForeignKey("code_symbols.id", ondelete="SET NULL"), nullable=True)
    chunk_type: Mapped[KnowledgeChunkType] = mapped_column(
        Enum(KnowledgeChunkType, name="knowledge_chunk_type", native_enum=True, values_callable=enum_values), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(Text, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    # Python 使用 metadata_ 避免与 SQLAlchemy Declarative 的 metadata 属性冲突。
    metadata_: Mapped[dict[str, object]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    # 维度与迁移中的 vector(1536) 保持一致，写入前由 Embedding Provider 校验。
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    embedding_status: Mapped[EmbeddingStatus] = mapped_column(
        Enum(EmbeddingStatus, name="embedding_status", native_enum=True, values_callable=enum_values),
        nullable=False,
        default=EmbeddingStatus.PENDING,
    )
    # 尝试次数用于限制重复失败时的自动或人工重试边界。
    embedding_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class BusinessRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """可追溯到项目扫描版本和符号的业务规则基础记录。"""

    __tablename__ = "business_rules"

    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    source_scan_id: Mapped[UUID] = mapped_column(ForeignKey("source_scans.id", ondelete="CASCADE"), nullable=False)
    source_symbol_id: Mapped[UUID | None] = mapped_column(ForeignKey("code_symbols.id", ondelete="SET NULL"), nullable=True)
    source_type: Mapped[BusinessRuleSourceType] = mapped_column(
        Enum(
            BusinessRuleSourceType,
            name="business_rule_source_type",
            native_enum=True,
            values_callable=enum_values,
        ),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
