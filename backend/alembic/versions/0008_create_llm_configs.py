"""创建 LLM 配置表。"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision: str = "0008_create_llm_configs"
down_revision: str | Sequence[str] | None = "0007_add_environment_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
def upgrade() -> None:
    op.create_table("llm_configs", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("name", sa.String(128), nullable=False, unique=True), sa.Column("provider", sa.String(64), nullable=False), sa.Column("base_url", sa.Text(), nullable=False), sa.Column("model", sa.String(256), nullable=False), sa.Column("encrypted_api_key", sa.Text(), nullable=False), sa.Column("context_window", sa.Integer(), nullable=False), sa.Column("temperature", sa.Float(), nullable=False, server_default=sa.text("0.2")), sa.Column("max_output_tokens", sa.Integer(), nullable=False), sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")), sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
def downgrade() -> None: op.drop_table("llm_configs")
