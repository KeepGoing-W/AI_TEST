"""启用 pgvector 扩展。"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_enable_pgvector"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """启用向量字段依赖的 PostgreSQL 扩展。"""

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """移除 pgvector 扩展。"""

    op.execute("DROP EXTENSION IF EXISTS vector")
