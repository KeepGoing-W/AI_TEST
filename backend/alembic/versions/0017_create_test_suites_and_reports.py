"""创建关联流程并扩展流程执行证据。"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0017_create_test_suites_and_reports"
down_revision: str | Sequence[str] | None = "0016_create_execution_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    extraction_source = postgresql.ENUM(
        "json_path", "response_header", "text", "status_code", name="variable_extraction_source"
    )
    extraction_source.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "test_suites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("stop_on_failure", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("idx_test_suites_project_updated", "test_suites", ["project_id", "updated_at"])
    op.create_table(
        "test_suite_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("test_suite_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("test_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "request_override", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["test_suite_id"], ["test_suites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["test_case_id"], ["test_cases.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("test_suite_id", "position", name="uq_test_suite_steps_position"),
    )
    op.create_table(
        "variable_extractions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("test_suite_step_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("variable_key", sa.String(length=128), nullable=False),
        sa.Column("source", extraction_source, nullable=False),
        sa.Column("expression", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["test_suite_step_id"], ["test_suite_steps.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("test_suite_step_id", "variable_key", name="uq_variable_extractions_step_key"),
    )
    op.add_column("execution_runs", sa.Column("test_suite_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_execution_runs_test_suite", "execution_runs", "test_suites", ["test_suite_id"], ["id"], ondelete="SET NULL"
    )
    op.add_column("execution_steps", sa.Column("test_suite_step_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "execution_steps",
        sa.Column("request_override", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "execution_steps",
        sa.Column("variable_extractions", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column(
        "execution_steps",
        sa.Column("extracted_variables", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_foreign_key(
        "fk_execution_steps_test_suite_step",
        "execution_steps",
        "test_suite_steps",
        ["test_suite_step_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "execution_diagnoses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("execution_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_step_id", postgresql.UUID(as_uuid=True)),
        sa.Column("failure_category", sa.String(length=64), nullable=False),
        sa.Column(
            "evidence_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "source_references", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("hypotheses", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["execution_run_id"], ["execution_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["execution_step_id"], ["execution_steps.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("idx_execution_diagnoses_run_created", "execution_diagnoses", ["execution_run_id", "created_at"])
    op.execute("ALTER TYPE execution_error_category ADD VALUE IF NOT EXISTS 'precondition'")
    op.execute("ALTER TYPE execution_error_category ADD VALUE IF NOT EXISTS 'variable_extraction'")


def downgrade() -> None:
    op.drop_index("idx_execution_diagnoses_run_created", table_name="execution_diagnoses")
    op.drop_table("execution_diagnoses")
    op.drop_constraint("fk_execution_steps_test_suite_step", "execution_steps", type_="foreignkey")
    op.drop_column("execution_steps", "extracted_variables")
    op.drop_column("execution_steps", "variable_extractions")
    op.drop_column("execution_steps", "request_override")
    op.drop_column("execution_steps", "test_suite_step_id")
    op.drop_constraint("fk_execution_runs_test_suite", "execution_runs", type_="foreignkey")
    op.drop_column("execution_runs", "test_suite_id")
    op.drop_table("variable_extractions")
    op.drop_table("test_suite_steps")
    op.drop_index("idx_test_suites_project_updated", table_name="test_suites")
    op.drop_table("test_suites")
    postgresql.ENUM(name="variable_extraction_source").drop(op.get_bind(), checkfirst=True)
