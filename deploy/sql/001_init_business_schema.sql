-- AI 接口测试 Agent 平台 MVP 业务表基线。
-- 目标数据库：PostgreSQL 16 + pgvector。

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TYPE user_role AS ENUM ('admin', 'test_member');
CREATE TYPE source_type AS ENUM ('local_path', 'zip_upload');
CREATE TYPE openapi_source_type AS ENUM ('url', 'file');
CREATE TYPE source_artifact_type AS ENUM ('source', 'openapi');
CREATE TYPE environment_type AS ENUM ('test', 'staging', 'production');
CREATE TYPE scan_status AS ENUM ('pending', 'running', 'succeeded', 'failed', 'cancelled');
CREATE TYPE symbol_type AS ENUM (
    'package', 'class', 'interface', 'enum', 'method', 'field', 'parameter', 'dto', 'exception', 'repository', 'mapper', 'sql'
);
CREATE TYPE relation_type AS ENUM (
    'calls', 'references', 'extends', 'implements', 'declares', 'throws', 'uses_dto', 'maps_to', 'contains'
);
CREATE TYPE rule_origin AS ENUM ('source_confirmed', 'inferred', 'human_confirmed', 'human_rejected');
CREATE TYPE testcase_category AS ENUM ('functional', 'boundary', 'exception', 'permission', 'workflow');
CREATE TYPE testcase_status AS ENUM ('draft', 'pending_review', 'approved', 'disabled');
CREATE TYPE testcase_priority AS ENUM ('low', 'medium', 'high', 'critical');
CREATE TYPE assertion_type AS ENUM (
    'status_code_equals', 'business_code_equals', 'json_path_equals', 'json_path_exists', 'json_path_not_exists',
    'json_path_type', 'body_contains', 'body_not_contains', 'number_range', 'response_time_less_than'
);
CREATE TYPE agent_run_type AS ENUM ('analysis', 'testcase_generation', 'failure_diagnosis');
CREATE TYPE agent_run_status AS ENUM ('pending', 'running', 'waiting_review', 'succeeded', 'failed', 'cancelled');
CREATE TYPE task_type AS ENUM ('source_scan', 'agent_run', 'testcase_run', 'testcase_batch_run', 'test_suite_run');
CREATE TYPE task_status AS ENUM ('pending', 'running', 'succeeded', 'failed', 'cancelled');
CREATE TYPE execution_type AS ENUM ('testcase', 'batch', 'test_suite');
CREATE TYPE execution_status AS ENUM ('pending', 'running', 'passed', 'failed', 'skipped', 'cancelled');
CREATE TYPE execution_step_status AS ENUM ('pending', 'running', 'passed', 'failed', 'skipped', 'cancelled');
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(64) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(128) NOT NULL,
    role user_role NOT NULL DEFAULT 'test_member',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_users_username UNIQUE (username)
);

CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    source_type source_type NOT NULL,
    source_location TEXT NOT NULL,
    openapi_source_type openapi_source_type,
    openapi_location TEXT,
    default_environment_id UUID,
    language VARCHAR(32) NOT NULL DEFAULT 'java',
    framework VARCHAR(32) NOT NULL DEFAULT 'spring_boot',
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_projects_language CHECK (language = 'java'),
    CONSTRAINT ck_projects_framework CHECK (framework = 'spring_boot'),
    CONSTRAINT ck_projects_openapi_source CHECK (
        (openapi_source_type IS NULL AND openapi_location IS NULL)
        OR (openapi_source_type IS NOT NULL AND openapi_location IS NOT NULL)
    )
);

CREATE TABLE project_members (
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (project_id, user_id)
);

CREATE TABLE source_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    artifact_type source_artifact_type NOT NULL,
    source_type source_type NOT NULL,
    storage_location TEXT NOT NULL,
    original_name VARCHAR(512),
    sha256 CHAR(64),
    size_bytes BIGINT,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_source_artifacts_size CHECK (size_bytes IS NULL OR size_bytes >= 0)
);

CREATE TABLE test_environments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name VARCHAR(128) NOT NULL,
    base_url TEXT NOT NULL,
    environment_type environment_type NOT NULL,
    common_headers JSONB NOT NULL DEFAULT '{}'::JSONB,
    host_allowlist JSONB NOT NULL DEFAULT '[]'::JSONB,
    allow_write_requests BOOLEAN NOT NULL DEFAULT FALSE,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_test_environments_project_name UNIQUE (project_id, name),
    CONSTRAINT ck_test_environments_production_readonly CHECK (
        environment_type <> 'production' OR allow_write_requests = FALSE
    ),
    CONSTRAINT ck_test_environments_host_allowlist_array CHECK (jsonb_typeof(host_allowlist) = 'array')
);

ALTER TABLE projects
    ADD CONSTRAINT fk_projects_default_environment
    FOREIGN KEY (default_environment_id) REFERENCES test_environments(id) ON DELETE SET NULL;

CREATE TABLE environment_variables (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    environment_id UUID NOT NULL REFERENCES test_environments(id) ON DELETE CASCADE,
    variable_key VARCHAR(128) NOT NULL,
    value TEXT,
    encrypted_value TEXT,
    is_secret BOOLEAN NOT NULL DEFAULT FALSE,
    description VARCHAR(512) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_environment_variables_key UNIQUE (environment_id, variable_key),
    CONSTRAINT ck_environment_variables_value CHECK (
        (is_secret = FALSE AND value IS NOT NULL AND encrypted_value IS NULL)
        OR (is_secret = TRUE AND value IS NULL AND encrypted_value IS NOT NULL)
    )
);

CREATE TABLE source_scans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_artifact_id UUID REFERENCES source_artifacts(id) ON DELETE SET NULL,
    scan_version INTEGER NOT NULL,
    status scan_status NOT NULL DEFAULT 'pending',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    summary JSONB NOT NULL DEFAULT '{}'::JSONB,
    error_code VARCHAR(128),
    error_message TEXT,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_source_scans_project_version UNIQUE (project_id, scan_version),
    CONSTRAINT ck_source_scans_time CHECK (completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at)
);

CREATE TABLE source_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_scan_id UUID NOT NULL REFERENCES source_scans(id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    language VARCHAR(32) NOT NULL DEFAULT 'java',
    content TEXT NOT NULL,
    content_sha256 CHAR(64) NOT NULL,
    size_bytes BIGINT NOT NULL,
    is_ignored BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_source_files_scan_path UNIQUE (source_scan_id, relative_path),
    CONSTRAINT ck_source_files_size CHECK (size_bytes >= 0)
);

CREATE TABLE code_symbols (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_scan_id UUID NOT NULL REFERENCES source_scans(id) ON DELETE CASCADE,
    source_file_id UUID NOT NULL REFERENCES source_files(id) ON DELETE CASCADE,
    parent_symbol_id UUID REFERENCES code_symbols(id) ON DELETE SET NULL,
    symbol_type symbol_type NOT NULL,
    name VARCHAR(512) NOT NULL,
    qualified_name TEXT NOT NULL,
    signature TEXT,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    annotations JSONB NOT NULL DEFAULT '[]'::JSONB,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_code_symbols_scan_qualified_name UNIQUE (source_scan_id, qualified_name),
    CONSTRAINT ck_code_symbols_line_range CHECK (start_line > 0 AND end_line >= start_line)
);

CREATE TABLE symbol_relations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_scan_id UUID NOT NULL REFERENCES source_scans(id) ON DELETE CASCADE,
    source_symbol_id UUID NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,
    target_symbol_id UUID NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,
    relation_type relation_type NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_symbol_relations_unique UNIQUE (source_symbol_id, target_symbol_id, relation_type)
);

CREATE TABLE api_definitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_scan_id UUID NOT NULL REFERENCES source_scans(id) ON DELETE CASCADE,
    method VARCHAR(10) NOT NULL,
    normalized_path TEXT NOT NULL,
    operation_id VARCHAR(256),
    controller_symbol_id UUID REFERENCES code_symbols(id) ON DELETE SET NULL,
    method_symbol_id UUID REFERENCES code_symbols(id) ON DELETE SET NULL,
    request_definition JSONB NOT NULL DEFAULT '{}'::JSONB,
    response_definition JSONB NOT NULL DEFAULT '{}'::JSONB,
    security_definition JSONB NOT NULL DEFAULT '{}'::JSONB,
    source_definition JSONB NOT NULL DEFAULT '{}'::JSONB,
    openapi_definition JSONB NOT NULL DEFAULT '{}'::JSONB,
    conflicts JSONB NOT NULL DEFAULT '[]'::JSONB,
    is_conflicted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_api_definitions_scan_route UNIQUE (source_scan_id, method, normalized_path),
    CONSTRAINT ck_api_definitions_method CHECK (method IN ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'))
);

CREATE TABLE business_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_scan_id UUID REFERENCES source_scans(id) ON DELETE SET NULL,
    api_definition_id UUID REFERENCES api_definitions(id) ON DELETE SET NULL,
    rule_type VARCHAR(64) NOT NULL,
    content TEXT NOT NULL,
    origin rule_origin NOT NULL,
    confidence NUMERIC(4, 3) NOT NULL DEFAULT 0,
    evidence JSONB NOT NULL DEFAULT '[]'::JSONB,
    created_by_agent_run_id UUID,
    confirmed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    confirmed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_business_rules_confidence CHECK (confidence >= 0 AND confidence <= 1)
);

CREATE TABLE knowledge_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_scan_id UUID NOT NULL REFERENCES source_scans(id) ON DELETE CASCADE,
    source_file_id UUID REFERENCES source_files(id) ON DELETE SET NULL,
    code_symbol_id UUID REFERENCES code_symbols(id) ON DELETE SET NULL,
    api_definition_id UUID REFERENCES api_definitions(id) ON DELETE SET NULL,
    business_rule_id UUID REFERENCES business_rules(id) ON DELETE SET NULL,
    chunk_type VARCHAR(64) NOT NULL,
    content TEXT NOT NULL,
    content_sha256 CHAR(64) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    embedding vector,
    embedding_model VARCHAR(256),
    embedded_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_knowledge_chunks_scan_hash UNIQUE (source_scan_id, content_sha256)
);

CREATE TABLE llm_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) NOT NULL,
    provider VARCHAR(64) NOT NULL,
    base_url TEXT NOT NULL,
    model VARCHAR(256) NOT NULL,
    encrypted_api_key TEXT NOT NULL,
    context_window INTEGER NOT NULL,
    temperature NUMERIC(3, 2) NOT NULL DEFAULT 0.20,
    max_output_tokens INTEGER NOT NULL,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_llm_configs_name UNIQUE (name),
    CONSTRAINT ck_llm_configs_context_window CHECK (context_window > 0),
    CONSTRAINT ck_llm_configs_temperature CHECK (temperature >= 0 AND temperature <= 2),
    CONSTRAINT ck_llm_configs_max_output_tokens CHECK (max_output_tokens > 0)
);

CREATE UNIQUE INDEX uq_llm_configs_default ON llm_configs (is_default) WHERE is_default;

CREATE TABLE agent_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_scan_id UUID REFERENCES source_scans(id) ON DELETE SET NULL,
    llm_config_id UUID REFERENCES llm_configs(id) ON DELETE SET NULL,
    run_type agent_run_type NOT NULL,
    status agent_run_status NOT NULL DEFAULT 'pending',
    prompt_version VARCHAR(128) NOT NULL,
    input_payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    output_payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    model_snapshot JSONB NOT NULL DEFAULT '{}'::JSONB,
    error_code VARCHAR(128),
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_agent_runs_time CHECK (completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at)
);

ALTER TABLE business_rules
    ADD CONSTRAINT fk_business_rules_agent_run
    FOREIGN KEY (created_by_agent_run_id) REFERENCES agent_runs(id) ON DELETE SET NULL;

CREATE TABLE agent_run_apis (
    agent_run_id UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    api_definition_id UUID NOT NULL REFERENCES api_definitions(id) ON DELETE RESTRICT,
    PRIMARY KEY (agent_run_id, api_definition_id)
);

CREATE TABLE agent_checkpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_run_id UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    checkpoint_key VARCHAR(256) NOT NULL,
    sequence_no INTEGER NOT NULL,
    state_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_agent_checkpoints_run_sequence UNIQUE (agent_run_id, sequence_no),
    CONSTRAINT uq_agent_checkpoints_run_key UNIQUE (agent_run_id, checkpoint_key),
    CONSTRAINT ck_agent_checkpoints_sequence CHECK (sequence_no >= 0)
);

CREATE TABLE test_suites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name VARCHAR(256) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    stop_on_failure BOOLEAN NOT NULL DEFAULT TRUE,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_test_suites_project_name UNIQUE (project_id, name)
);

CREATE TABLE test_cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    api_definition_id UUID REFERENCES api_definitions(id) ON DELETE SET NULL,
    source_scan_id UUID REFERENCES source_scans(id) ON DELETE SET NULL,
    generated_by_agent_run_id UUID REFERENCES agent_runs(id) ON DELETE SET NULL,
    name VARCHAR(256) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category testcase_category NOT NULL,
    priority testcase_priority NOT NULL DEFAULT 'medium',
    status testcase_status NOT NULL DEFAULT 'draft',
    version INTEGER NOT NULL DEFAULT 1,
    preconditions JSONB NOT NULL DEFAULT '[]'::JSONB,
    request_template JSONB NOT NULL DEFAULT '{}'::JSONB,
    variable_extraction_rules JSONB NOT NULL DEFAULT '[]'::JSONB,
    cleanup_instructions TEXT NOT NULL DEFAULT '',
    ai_confidence NUMERIC(4, 3),
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    approved_by UUID REFERENCES users(id) ON DELETE SET NULL,
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_test_cases_version CHECK (version > 0),
    CONSTRAINT ck_test_cases_confidence CHECK (ai_confidence IS NULL OR (ai_confidence >= 0 AND ai_confidence <= 1))
);

CREATE TABLE test_case_business_rules (
    test_case_id UUID NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
    business_rule_id UUID NOT NULL REFERENCES business_rules(id) ON DELETE RESTRICT,
    PRIMARY KEY (test_case_id, business_rule_id)
);

CREATE TABLE test_case_symbols (
    test_case_id UUID NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
    code_symbol_id UUID NOT NULL REFERENCES code_symbols(id) ON DELETE RESTRICT,
    PRIMARY KEY (test_case_id, code_symbol_id)
);

CREATE TABLE test_assertions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    test_case_id UUID NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
    sequence_no INTEGER NOT NULL,
    assertion_type assertion_type NOT NULL,
    json_path TEXT,
    expected_value JSONB,
    config JSONB NOT NULL DEFAULT '{}'::JSONB,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_test_assertions_case_sequence UNIQUE (test_case_id, sequence_no),
    CONSTRAINT ck_test_assertions_sequence CHECK (sequence_no >= 0)
);

CREATE TABLE test_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    test_suite_id UUID NOT NULL REFERENCES test_suites(id) ON DELETE CASCADE,
    test_case_id UUID NOT NULL REFERENCES test_cases(id) ON DELETE RESTRICT,
    sequence_no INTEGER NOT NULL,
    request_override JSONB NOT NULL DEFAULT '{}'::JSONB,
    extraction_rules JSONB NOT NULL DEFAULT '[]'::JSONB,
    stop_on_failure BOOLEAN,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_test_steps_suite_sequence UNIQUE (test_suite_id, sequence_no),
    CONSTRAINT ck_test_steps_sequence CHECK (sequence_no >= 0)
);

CREATE TABLE execution_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    environment_id UUID NOT NULL REFERENCES test_environments(id) ON DELETE RESTRICT,
    source_scan_id UUID REFERENCES source_scans(id) ON DELETE SET NULL,
    test_case_id UUID REFERENCES test_cases(id) ON DELETE SET NULL,
    test_suite_id UUID REFERENCES test_suites(id) ON DELETE SET NULL,
    execution_type execution_type NOT NULL,
    status execution_status NOT NULL DEFAULT 'pending',
    target_host TEXT NOT NULL,
    config_snapshot JSONB NOT NULL DEFAULT '{}'::JSONB,
    runtime_variables JSONB NOT NULL DEFAULT '{}'::JSONB,
    summary JSONB NOT NULL DEFAULT '{}'::JSONB,
    error_code VARCHAR(128),
    error_message TEXT,
    requested_by UUID REFERENCES users(id) ON DELETE SET NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_execution_runs_target CHECK (length(target_host) > 0),
    CONSTRAINT ck_execution_runs_duration CHECK (duration_ms IS NULL OR duration_ms >= 0),
    CONSTRAINT ck_execution_runs_time CHECK (completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at),
    CONSTRAINT ck_execution_runs_target_type CHECK (
        (execution_type = 'testcase' AND test_case_id IS NOT NULL AND test_suite_id IS NULL)
        OR (execution_type = 'test_suite' AND test_case_id IS NULL AND test_suite_id IS NOT NULL)
        OR (execution_type = 'batch' AND test_case_id IS NULL AND test_suite_id IS NULL)
    )
);

CREATE TABLE execution_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_run_id UUID NOT NULL REFERENCES execution_runs(id) ON DELETE CASCADE,
    test_step_id UUID REFERENCES test_steps(id) ON DELETE SET NULL,
    test_case_id UUID REFERENCES test_cases(id) ON DELETE SET NULL,
    sequence_no INTEGER NOT NULL,
    status execution_step_status NOT NULL DEFAULT 'pending',
    test_case_snapshot JSONB NOT NULL DEFAULT '{}'::JSONB,
    request_snapshot JSONB NOT NULL DEFAULT '{}'::JSONB,
    response_snapshot JSONB NOT NULL DEFAULT '{}'::JSONB,
    extracted_variables JSONB NOT NULL DEFAULT '{}'::JSONB,
    curl_command TEXT,
    error_code VARCHAR(128),
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_execution_steps_run_sequence UNIQUE (execution_run_id, sequence_no),
    CONSTRAINT ck_execution_steps_sequence CHECK (sequence_no >= 0),
    CONSTRAINT ck_execution_steps_duration CHECK (duration_ms IS NULL OR duration_ms >= 0),
    CONSTRAINT ck_execution_steps_time CHECK (completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at)
);

CREATE TABLE assertion_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_step_id UUID NOT NULL REFERENCES execution_steps(id) ON DELETE CASCADE,
    test_assertion_id UUID REFERENCES test_assertions(id) ON DELETE SET NULL,
    assertion_type assertion_type NOT NULL,
    json_path TEXT,
    expected_value JSONB,
    actual_value JSONB,
    passed BOOLEAN,
    message TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE background_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    task_type task_type NOT NULL,
    status task_status NOT NULL DEFAULT 'pending',
    payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    result JSONB NOT NULL DEFAULT '{}'::JSONB,
    error_code VARCHAR(128),
    error_message TEXT,
    requested_by UUID REFERENCES users(id) ON DELETE SET NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_background_tasks_time CHECK (completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at)
);

CREATE INDEX idx_projects_created_by ON projects(created_by);
CREATE INDEX idx_project_members_user ON project_members(user_id);
CREATE INDEX idx_source_artifacts_project ON source_artifacts(project_id, artifact_type, created_at DESC);
CREATE INDEX idx_test_environments_project ON test_environments(project_id);
CREATE INDEX idx_source_scans_project_status ON source_scans(project_id, status, created_at DESC);
CREATE INDEX idx_source_files_scan ON source_files(source_scan_id);
CREATE INDEX idx_code_symbols_scan_type_name ON code_symbols(source_scan_id, symbol_type, name);
CREATE INDEX idx_code_symbols_file ON code_symbols(source_file_id);
CREATE INDEX idx_symbol_relations_source ON symbol_relations(source_symbol_id, relation_type);
CREATE INDEX idx_symbol_relations_target ON symbol_relations(target_symbol_id, relation_type);
CREATE INDEX idx_api_definitions_project_route ON api_definitions(project_id, method, normalized_path);
CREATE INDEX idx_business_rules_project_api ON business_rules(project_id, api_definition_id, origin);
CREATE INDEX idx_knowledge_chunks_project_scan ON knowledge_chunks(project_id, source_scan_id, chunk_type);
CREATE INDEX idx_agent_runs_project_status ON agent_runs(project_id, status, created_at DESC);
CREATE INDEX idx_test_cases_project_status ON test_cases(project_id, status, category);
CREATE INDEX idx_test_cases_api ON test_cases(api_definition_id);
CREATE INDEX idx_execution_runs_project_status ON execution_runs(project_id, status, created_at DESC);
CREATE INDEX idx_execution_runs_environment ON execution_runs(environment_id, created_at DESC);
CREATE INDEX idx_execution_steps_run ON execution_steps(execution_run_id, sequence_no);
CREATE INDEX idx_assertion_results_step ON assertion_results(execution_step_id);
CREATE INDEX idx_background_tasks_project_status ON background_tasks(project_id, status, created_at DESC);

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_projects_updated_at BEFORE UPDATE ON projects
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_test_environments_updated_at BEFORE UPDATE ON test_environments
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_environment_variables_updated_at BEFORE UPDATE ON environment_variables
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_api_definitions_updated_at BEFORE UPDATE ON api_definitions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_business_rules_updated_at BEFORE UPDATE ON business_rules
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_llm_configs_updated_at BEFORE UPDATE ON llm_configs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_test_suites_updated_at BEFORE UPDATE ON test_suites
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_test_cases_updated_at BEFORE UPDATE ON test_cases
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_test_assertions_updated_at BEFORE UPDATE ON test_assertions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_test_steps_updated_at BEFORE UPDATE ON test_steps
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_background_tasks_updated_at BEFORE UPDATE ON background_tasks
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;
