"""固化用例版本和执行追溯快照。"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0018_add_execution_traceability_snapshots"
down_revision: str | Sequence[str] | None = "0017_create_test_suites_and_reports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("test_cases", sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")))
    op.add_column(
        "execution_steps",
        sa.Column("case_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "execution_steps",
        sa.Column(
            "traceability_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("execution_steps", "traceability_snapshot")
    op.drop_column("execution_steps", "case_snapshot")
    op.drop_column("test_cases", "version")
