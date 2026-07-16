"""创建执行记录、执行步骤和断言结果表。"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0016_create_execution_models"
down_revision: str | Sequence[str] | None = "0015_create_agent_and_testcase_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE task_type ADD VALUE IF NOT EXISTS 'execution'")
    run_status = postgresql.ENUM("pending", "running", "completed", "failed", "stopped", name="execution_run_status")
    step_status = postgresql.ENUM(
        "pending", "running", "passed", "failed", "error", "skipped", "stopped", name="execution_step_status"
    )
    error_category = postgresql.ENUM(
        "request_build", "security", "dns", "connection", "tls", "timeout", "response_too_large", "assertion", "internal",
        name="execution_error_category",
    )
    for enum_type in (run_status, step_status, error_category):
        enum_type.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "execution_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("environment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("background_task_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True)),
        sa.Column("status", run_status, nullable=False, server_default=sa.text("'pending'")),
        sa.Column("stop_on_failure", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("runtime_variables", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("passed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_code", sa.String(length=128)),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["environment_id"], ["test_environments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["background_task_id"], ["background_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("idx_execution_runs_project_created", "execution_runs", ["project_id", "created_at"])
    op.create_table(
        "execution_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("execution_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("test_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", step_status, nullable=False, server_default=sa.text("'pending'")),
        sa.Column("method", sa.String(length=10)),
        sa.Column("target_url", sa.Text()),
        sa.Column("request_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("response_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("redacted_curl", sa.Text()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("error_category", error_category),
        sa.Column("error_code", sa.String(length=128)),
        sa.Column("error_message", sa.Text()),
        sa.Column("skip_reason", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["execution_run_id"], ["execution_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_case_id"], ["test_cases.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("execution_run_id", "position", name="uq_execution_steps_run_position"),
    )
    op.create_index("idx_execution_steps_run_status", "execution_steps", ["execution_run_id", "status", "position"])
    op.create_table(
        "assertion_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("execution_step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("assertion_type", sa.String(length=64), nullable=False),
        sa.Column("path", sa.Text()),
        sa.Column("expected", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("actual", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["execution_step_id"], ["execution_steps.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("execution_step_id", "position", name="uq_assertion_results_step_position"),
    )
    op.create_index("idx_assertion_results_step", "assertion_results", ["execution_step_id", "position"])


def downgrade() -> None:
    op.drop_index("idx_assertion_results_step", table_name="assertion_results")
    op.drop_table("assertion_results")
    op.drop_index("idx_execution_steps_run_status", table_name="execution_steps")
    op.drop_table("execution_steps")
    op.drop_index("idx_execution_runs_project_created", table_name="execution_runs")
    op.drop_table("execution_runs")
    for name in ("execution_error_category", "execution_step_status", "execution_run_status"):
        postgresql.ENUM(name=name).drop(op.get_bind(), checkfirst=True)
