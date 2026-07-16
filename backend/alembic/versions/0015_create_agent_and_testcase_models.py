"""创建 Agent 运行、检查点、测试用例和断言表。"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0015_create_agent_and_testcase_models"
down_revision: str | Sequence[str] | None = "0014_add_knowledge_embeddings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    agent_run_status = postgresql.ENUM(
        "pending", "running", "pending_review", "approved", "disabled", "failed", name="agent_run_status"
    )
    agent_error_category = postgresql.ENUM(
        "input", "retrieval", "model", "output", "interrupt", "recovery", name="agent_error_category"
    )
    test_case_category = postgresql.ENUM(
        "functional", "boundary", "exception", "permission", name="test_case_category"
    )
    test_case_status = postgresql.ENUM("draft", "pending_review", "approved", "disabled", name="test_case_status")
    for enum_type in (agent_run_status, agent_error_category, test_case_category, test_case_status):
        enum_type.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_scan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("llm_config_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("api_definition_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", agent_run_status, nullable=False, server_default=sa.text("'pending'")),
        sa.Column("current_node", sa.String(length=128), nullable=False, server_default=sa.text("'validate_input'")),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("model_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("state_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_category", agent_error_category),
        sa.Column("error_code", sa.String(length=128)),
        sa.Column("error_message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_scan_id"], ["source_scans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["llm_config_id"], ["llm_configs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("idx_agent_runs_project_created", "agent_runs", ["project_id", "created_at"])
    op.create_table(
        "agent_checkpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("node_name", sa.String(length=128), nullable=False),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("agent_run_id", "sequence", name="uq_agent_checkpoints_run_sequence"),
    )
    op.create_index("idx_agent_checkpoints_run", "agent_checkpoints", ["agent_run_id", "sequence"])
    op.create_table(
        "test_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_scan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("api_definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("category", test_case_category, nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default=sa.text("'P1'")),
        sa.Column("status", test_case_status, nullable=False, server_default=sa.text("'draft'")),
        sa.Column("preconditions", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("request_template", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source_rule_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("source_symbol_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("is_inferred", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_scan_id"], ["source_scans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["api_definition_id"], ["api_definitions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("idx_test_cases_project_api", "test_cases", ["project_id", "api_definition_id"])
    op.create_index("idx_test_cases_project_status", "test_cases", ["project_id", "status"])
    op.create_table(
        "test_assertions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("test_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("assertion_type", sa.String(length=64), nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["test_case_id"], ["test_cases.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("test_case_id", "position", name="uq_test_assertions_case_position"),
    )


def downgrade() -> None:
    op.drop_table("test_assertions")
    op.drop_index("idx_test_cases_project_status", table_name="test_cases")
    op.drop_index("idx_test_cases_project_api", table_name="test_cases")
    op.drop_table("test_cases")
    op.drop_index("idx_agent_checkpoints_run", table_name="agent_checkpoints")
    op.drop_table("agent_checkpoints")
    op.drop_index("idx_agent_runs_project_created", table_name="agent_runs")
    op.drop_table("agent_runs")
    for name in ("test_case_status", "test_case_category", "agent_error_category", "agent_run_status"):
        postgresql.ENUM(name=name).drop(op.get_bind(), checkfirst=True)
