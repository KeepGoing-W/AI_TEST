"""创建代码符号与源码接口定义表。"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0011_create_code_symbols_and_api_definitions"
down_revision: str | Sequence[str] | None = "0010_create_source_files"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    symbol_type = postgresql.ENUM("class", "interface", "enum", "method", name="symbol_type")
    symbol_type.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "code_symbols",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_scan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_symbol_id", postgresql.UUID(as_uuid=True)),
        sa.Column("symbol_type", symbol_type, nullable=False),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("qualified_name", sa.Text(), nullable=False),
        sa.Column("signature", sa.Text()),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column(
            "annotations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(["source_scan_id"], ["source_scans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_symbol_id"], ["code_symbols.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("source_scan_id", "qualified_name", name="uq_code_symbols_scan_qualified_name"),
        sa.CheckConstraint("start_line > 0 AND end_line >= start_line", name="ck_code_symbols_line_range"),
    )
    op.create_index("idx_code_symbols_scan_type_name", "code_symbols", ["source_scan_id", "symbol_type", "name"])
    op.create_index("idx_code_symbols_file", "code_symbols", ["source_file_id"])
    op.create_table(
        "api_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_scan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("normalized_path", sa.Text(), nullable=False),
        sa.Column("operation_id", sa.String(length=256)),
        sa.Column("controller_symbol_id", postgresql.UUID(as_uuid=True)),
        sa.Column("method_symbol_id", postgresql.UUID(as_uuid=True)),
        sa.Column(
            "request_definition",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "response_definition",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "security_definition",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "source_definition",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "openapi_definition",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "conflicts", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("is_conflicted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_scan_id"], ["source_scans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["controller_symbol_id"], ["code_symbols.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["method_symbol_id"], ["code_symbols.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("source_scan_id", "method", "normalized_path", name="uq_api_definitions_scan_route"),
        sa.CheckConstraint("method IN ('GET', 'POST', 'PUT', 'PATCH', 'DELETE')", name="ck_api_definitions_method"),
    )
    op.create_index("idx_api_definitions_project_route", "api_definitions", ["project_id", "method", "normalized_path"])


def downgrade() -> None:
    op.drop_index("idx_api_definitions_project_route", table_name="api_definitions")
    op.drop_table("api_definitions")
    op.drop_index("idx_code_symbols_file", table_name="code_symbols")
    op.drop_index("idx_code_symbols_scan_type_name", table_name="code_symbols")
    op.drop_table("code_symbols")
    postgresql.ENUM(name="symbol_type").drop(op.get_bind(), checkfirst=True)
