"""创建源码来源表。"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004_create_source_artifacts"
down_revision: str | Sequence[str] | None = "0003_create_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    source_type = postgresql.ENUM("local_path", "zip_upload", name="source_type")
    source_type.create(op.get_bind(), checkfirst=True)
    op.create_table("source_artifacts", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("source_type", source_type, nullable=False), sa.Column("storage_location", sa.Text(), nullable=False), sa.Column("original_name", sa.String(length=512)), sa.Column("size_bytes", sa.Integer()), sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"))
    op.create_index("idx_source_artifacts_project", "source_artifacts", ["project_id"])


def downgrade() -> None:
    op.drop_index("idx_source_artifacts_project", table_name="source_artifacts")
    op.drop_table("source_artifacts")
    postgresql.ENUM(name="source_type").drop(op.get_bind(), checkfirst=True)
