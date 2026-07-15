"""为知识切块增加 pgvector Embedding 与状态。"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0014_add_knowledge_embeddings"
down_revision: str | Sequence[str] | None = "0013_create_knowledge_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE task_type ADD VALUE IF NOT EXISTS 'knowledge_embedding'")
    embedding_status = postgresql.ENUM("pending", "processing", "succeeded", "failed", name="embedding_status")
    embedding_status.create(op.get_bind(), checkfirst=True)
    op.add_column("knowledge_chunks", sa.Column("embedding", Vector(1536), nullable=True))
    op.add_column(
        "knowledge_chunks",
        sa.Column("embedding_status", embedding_status, nullable=False, server_default=sa.text("'pending'")),
    )
    op.add_column(
        "knowledge_chunks",
        sa.Column("embedding_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("knowledge_chunks", sa.Column("embedding_error", sa.Text(), nullable=True))
    op.create_index(
        "idx_knowledge_chunks_embedding",
        "knowledge_chunks",
        ["embedding"],
        postgresql_using="ivfflat",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"lists": 100},
    )
    op.create_index(
        "idx_knowledge_chunks_embedding_status",
        "knowledge_chunks",
        ["source_scan_id", "embedding_status", "embedding_attempts"],
    )


def downgrade() -> None:
    op.drop_index("idx_knowledge_chunks_embedding_status", table_name="knowledge_chunks")
    op.drop_index("idx_knowledge_chunks_embedding", table_name="knowledge_chunks")
    op.drop_column("knowledge_chunks", "embedding_error")
    op.drop_column("knowledge_chunks", "embedding_attempts")
    op.drop_column("knowledge_chunks", "embedding_status")
    op.drop_column("knowledge_chunks", "embedding")
    postgresql.ENUM(name="embedding_status").drop(op.get_bind(), checkfirst=True)
