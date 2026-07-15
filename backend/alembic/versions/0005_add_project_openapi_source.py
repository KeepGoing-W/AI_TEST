"""增加项目 OpenAPI 来源。"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005_add_project_openapi_source"
down_revision: str | Sequence[str] | None = "0004_create_source_artifacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    source_type = postgresql.ENUM("url", "file", name="openapi_source_type")
    source_type.create(op.get_bind(), checkfirst=True)
    op.add_column("projects", sa.Column("openapi_source_type", source_type, nullable=True))
    op.add_column("projects", sa.Column("openapi_location", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "openapi_location")
    op.drop_column("projects", "openapi_source_type")
    postgresql.ENUM(name="openapi_source_type").drop(op.get_bind(), checkfirst=True)
