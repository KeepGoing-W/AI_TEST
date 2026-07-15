"""创建源码文件快照表。"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0010_create_source_files"
down_revision: str | Sequence[str] | None = "0009_create_source_scan_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "source_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source_scan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False, server_default=sa.text("'java'")),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("is_ignored", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["source_scan_id"], ["source_scans.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_scan_id", "relative_path", name="uq_source_files_scan_path"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_source_files_size"),
    )
    op.create_index("idx_source_files_scan", "source_files", ["source_scan_id"])


def downgrade() -> None:
    op.drop_index("idx_source_files_scan", table_name="source_files")
    op.drop_table("source_files")
