"""增加环境请求配置字段。"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision: str = "0007_add_environment_config"
down_revision: str | Sequence[str] | None = "0006_create_test_environments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
def upgrade() -> None:
    op.add_column("test_environments", sa.Column("common_headers", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("test_environments", sa.Column("host_allowlist", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
def downgrade() -> None:
    op.drop_column("test_environments", "host_allowlist")
    op.drop_column("test_environments", "common_headers")
