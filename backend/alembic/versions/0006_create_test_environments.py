"""创建测试环境表。"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision: str = "0006_create_test_environments"
down_revision: str | Sequence[str] | None = "0005_add_project_openapi_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
def upgrade() -> None:
    kind = postgresql.ENUM("test", "staging", "production", name="environment_type")
    kind.create(op.get_bind(), checkfirst=True)
    op.create_table("test_environments", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("name", sa.String(128), nullable=False), sa.Column("base_url", sa.Text(), nullable=False), sa.Column("environment_type", kind, nullable=False), sa.Column("allow_write_requests", sa.Boolean(), nullable=False, server_default=sa.text("false")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"), sa.UniqueConstraint("project_id", "name"))
    op.create_table("environment_variables", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("environment_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("variable_key", sa.String(128), nullable=False), sa.Column("value", sa.Text()), sa.Column("encrypted_value", sa.Text()), sa.Column("is_secret", sa.Boolean(), nullable=False, server_default=sa.text("false")), sa.ForeignKeyConstraint(["environment_id"], ["test_environments.id"], ondelete="CASCADE"), sa.UniqueConstraint("environment_id", "variable_key"))
def downgrade() -> None:
    op.drop_table("environment_variables"); op.drop_table("test_environments"); postgresql.ENUM(name="environment_type").drop(op.get_bind(), checkfirst=True)
