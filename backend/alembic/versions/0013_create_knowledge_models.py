"""创建知识切块和业务规则基础表。"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0013_create_knowledge_models"
down_revision: str | Sequence[str] | None = "0012_expand_symbols_and_create_relations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    knowledge_chunk_type = postgresql.ENUM("class", "method", "dto", "sql", "exception", name="knowledge_chunk_type")
    business_rule_source_type = postgresql.ENUM("source_confirmed", "inferred", name="business_rule_source_type")
    knowledge_chunk_type.create(op.get_bind(), checkfirst=True)
    business_rule_source_type.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_scan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_symbol_id", postgresql.UUID(as_uuid=True)),
        sa.Column("chunk_type", knowledge_chunk_type, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_scan_id"], ["source_scans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["code_symbol_id"], ["code_symbols.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("source_scan_id", "source_file_id", "chunk_type", "start_line", "end_line", "code_symbol_id", name="uq_knowledge_chunks_scan_source_range"),
        sa.CheckConstraint("start_line > 0 AND end_line >= start_line", name="ck_knowledge_chunks_line_range"),
    )
    op.create_index("idx_knowledge_chunks_scan_type", "knowledge_chunks", ["source_scan_id", "chunk_type"])
    op.create_index("idx_knowledge_chunks_symbol", "knowledge_chunks", ["code_symbol_id"])
    op.create_table(
        "business_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_scan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_symbol_id", postgresql.UUID(as_uuid=True)),
        sa.Column("source_type", business_rule_source_type, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_scan_id"], ["source_scans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_symbol_id"], ["code_symbols.id"], ondelete="SET NULL"),
    )
    op.create_index("idx_business_rules_project_scan", "business_rules", ["project_id", "source_scan_id"])


def downgrade() -> None:
    op.drop_index("idx_business_rules_project_scan", table_name="business_rules")
    op.drop_table("business_rules")
    op.drop_index("idx_knowledge_chunks_symbol", table_name="knowledge_chunks")
    op.drop_index("idx_knowledge_chunks_scan_type", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    postgresql.ENUM(name="business_rule_source_type").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="knowledge_chunk_type").drop(op.get_bind(), checkfirst=True)
