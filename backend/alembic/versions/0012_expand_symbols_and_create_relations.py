"""扩展符号类型并创建符号关系表。"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0012_expand_symbols_and_create_relations"
down_revision: str | Sequence[str] | None = "0011_create_code_symbols_and_api_definitions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for value in ("field", "dto", "exception", "repository", "mapper"):
        op.execute(f"ALTER TYPE symbol_type ADD VALUE IF NOT EXISTS '{value}'")
    relation_type = postgresql.ENUM("calls", "references", "throws", "uses_dto", name="relation_type")
    relation_type.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "symbol_relations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_scan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_symbol_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_symbol_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", relation_type, nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(["source_scan_id"], ["source_scans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_symbol_id"], ["code_symbols.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_symbol_id"], ["code_symbols.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_symbol_id", "target_symbol_id", "relation_type", name="uq_symbol_relations_unique"),
    )
    op.create_index("idx_symbol_relations_source", "symbol_relations", ["source_symbol_id", "relation_type"])
    op.create_index("idx_symbol_relations_target", "symbol_relations", ["target_symbol_id", "relation_type"])


def downgrade() -> None:
    op.drop_index("idx_symbol_relations_target", table_name="symbol_relations")
    op.drop_index("idx_symbol_relations_source", table_name="symbol_relations")
    op.drop_table("symbol_relations")
    postgresql.ENUM(name="relation_type").drop(op.get_bind(), checkfirst=True)
