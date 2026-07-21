-- AI 接口测试 Agent 平台 MVP 业务表全量初始化脚本。
-- 目标数据库：PostgreSQL 16 + pgvector。
-- 结构版本：0018_add_execution_traceability_snapshots。
-- 仅用于空数据库初始化；已存在业务表时请使用 Alembic 增量迁移。
-- 执行前必须由 PostgreSQL 超级用户在目标数据库运行：CREATE EXTENSION IF NOT EXISTS vector;

BEGIN;

CREATE TYPE user_role AS ENUM ('admin', 'test_member');
CREATE TYPE source_type AS ENUM ('local_path', 'zip_upload');
CREATE TYPE openapi_source_type AS ENUM ('url', 'file');
CREATE TYPE environment_type AS ENUM ('test', 'staging', 'production');
CREATE TYPE task_type AS ENUM ('source_scan', 'knowledge_embedding', 'execution');
CREATE TYPE task_status AS ENUM ('pending', 'running', 'succeeded', 'failed', 'cancelled');
CREATE TYPE scan_status AS ENUM ('pending', 'running', 'succeeded', 'failed', 'cancelled');
CREATE TYPE symbol_type AS ENUM (
    'class', 'interface', 'enum', 'method', 'field', 'dto', 'exception', 'repository', 'mapper'
);
CREATE TYPE relation_type AS ENUM ('calls', 'references', 'throws', 'uses_dto');
CREATE TYPE knowledge_chunk_type AS ENUM ('class', 'method', 'dto', 'sql', 'exception');
CREATE TYPE business_rule_source_type AS ENUM ('source_confirmed', 'inferred');
CREATE TYPE embedding_status AS ENUM ('pending', 'processing', 'succeeded', 'failed');
CREATE TYPE agent_run_status AS ENUM ('pending', 'running', 'pending_review', 'approved', 'disabled', 'failed');
CREATE TYPE agent_error_category AS ENUM ('input', 'retrieval', 'model', 'output', 'interrupt', 'recovery');
CREATE TYPE test_case_category AS ENUM ('functional', 'boundary', 'exception', 'permission');
CREATE TYPE test_case_status AS ENUM ('draft', 'pending_review', 'approved', 'disabled');
CREATE TYPE execution_run_status AS ENUM ('pending', 'running', 'completed', 'failed', 'stopped');
CREATE TYPE execution_step_status AS ENUM ('pending', 'running', 'passed', 'failed', 'error', 'skipped', 'stopped');
CREATE TYPE execution_error_category AS ENUM (
    'request_build', 'security', 'dns', 'connection', 'tls', 'timeout', 'response_too_large', 'assertion',
    'internal', 'precondition', 'variable_extraction'
);
CREATE TYPE variable_extraction_source AS ENUM ('json_path', 'response_header', 'text', 'status_code');

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
    language VARCHAR(32) NOT NULL DEFAULT 'java',
    framework VARCHAR(32) NOT NULL DEFAULT 'spring_boot',
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    openapi_source_type openapi_source_type,
    openapi_location TEXT,
    CONSTRAINT ck_projects_language CHECK (language = 'java'),
    CONSTRAINT ck_projects_framework CHECK (framework = 'spring_boot')
);

CREATE INDEX idx_projects_created_by ON projects (created_by);

CREATE TABLE project_members (
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (project_id, user_id)
);

CREATE INDEX idx_project_members_user ON project_members (user_id);

CREATE TABLE source_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_type source_type NOT NULL,
    storage_location TEXT NOT NULL,
    original_name VARCHAR(512),
    size_bytes INTEGER,
    created_by UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_source_artifacts_project ON source_artifacts (project_id);

CREATE TABLE test_environments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name VARCHAR(128) NOT NULL,
    base_url TEXT NOT NULL,
    environment_type environment_type NOT NULL,
    allow_write_requests BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    common_headers JSONB NOT NULL DEFAULT '{}'::JSONB,
    host_allowlist JSONB NOT NULL DEFAULT '[]'::JSONB,
    CONSTRAINT test_environments_project_id_name_key UNIQUE (project_id, name)
);

CREATE TABLE environment_variables (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    environment_id UUID NOT NULL REFERENCES test_environments(id) ON DELETE CASCADE,
    variable_key VARCHAR(128) NOT NULL,
    value TEXT,
    encrypted_value TEXT,
    is_secret BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT environment_variables_environment_id_variable_key_key UNIQUE (environment_id, variable_key)
);

CREATE TABLE llm_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) NOT NULL,
    provider VARCHAR(64) NOT NULL,
    base_url TEXT NOT NULL,
    model VARCHAR(256) NOT NULL,
    encrypted_api_key TEXT NOT NULL,
    context_window INTEGER NOT NULL,
    temperature DOUBLE PRECISION NOT NULL DEFAULT 0.2,
    max_output_tokens INTEGER NOT NULL,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT llm_configs_name_key UNIQUE (name)
);

CREATE TABLE background_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
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
    CONSTRAINT ck_background_tasks_time CHECK (
        completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at
    )
);

CREATE INDEX idx_background_tasks_project_status
    ON background_tasks (project_id, status, created_at);

CREATE TABLE source_scans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_artifact_id UUID REFERENCES source_artifacts(id) ON DELETE SET NULL,
    background_task_id UUID NOT NULL REFERENCES background_tasks(id) ON DELETE CASCADE,
    scan_version INTEGER NOT NULL,
    status scan_status NOT NULL DEFAULT 'pending',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    summary JSONB NOT NULL DEFAULT '{}'::JSONB,
    error_code VARCHAR(128),
    error_message TEXT,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT source_scans_background_task_id_key UNIQUE (background_task_id),
    CONSTRAINT uq_source_scans_project_version UNIQUE (project_id, scan_version),
    CONSTRAINT ck_source_scans_time CHECK (
        completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at
    )
);

CREATE INDEX idx_source_scans_project_status
    ON source_scans (project_id, status, created_at);

CREATE TABLE source_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_scan_id UUID NOT NULL REFERENCES source_scans(id) ON DELETE CASCADE,
    relative_path TEXT NOT NULL,
    language VARCHAR(32) NOT NULL DEFAULT 'java',
    content TEXT NOT NULL,
    content_sha256 VARCHAR(64) NOT NULL,
    size_bytes BIGINT NOT NULL,
    is_ignored BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_source_files_scan_path UNIQUE (source_scan_id, relative_path),
    CONSTRAINT ck_source_files_size CHECK (size_bytes >= 0)
);

CREATE INDEX idx_source_files_scan ON source_files (source_scan_id);

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

CREATE INDEX idx_code_symbols_scan_type_name
    ON code_symbols (source_scan_id, symbol_type, name);
CREATE INDEX idx_code_symbols_file ON code_symbols (source_file_id);

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

CREATE INDEX idx_api_definitions_project_route
    ON api_definitions (project_id, method, normalized_path);

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

CREATE INDEX idx_symbol_relations_source
    ON symbol_relations (source_symbol_id, relation_type);
CREATE INDEX idx_symbol_relations_target
    ON symbol_relations (target_symbol_id, relation_type);

CREATE TABLE knowledge_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_scan_id UUID NOT NULL REFERENCES source_scans(id) ON DELETE CASCADE,
    source_file_id UUID NOT NULL REFERENCES source_files(id) ON DELETE CASCADE,
    code_symbol_id UUID REFERENCES code_symbols(id) ON DELETE SET NULL,
    chunk_type knowledge_chunk_type NOT NULL,
    content TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    embedding VECTOR(1536),
    embedding_status embedding_status NOT NULL DEFAULT 'pending',
    embedding_attempts INTEGER NOT NULL DEFAULT 0,
    embedding_error TEXT,
    CONSTRAINT uq_knowledge_chunks_scan_source_range UNIQUE (
        source_scan_id, source_file_id, chunk_type, start_line, end_line, code_symbol_id
    ),
    CONSTRAINT ck_knowledge_chunks_line_range CHECK (start_line > 0 AND end_line >= start_line)
);

CREATE INDEX idx_knowledge_chunks_scan_type
    ON knowledge_chunks (source_scan_id, chunk_type);
CREATE INDEX idx_knowledge_chunks_symbol ON knowledge_chunks (code_symbol_id);
CREATE INDEX idx_knowledge_chunks_embedding
    ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_knowledge_chunks_embedding_status
    ON knowledge_chunks (source_scan_id, embedding_status, embedding_attempts);

CREATE TABLE business_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_scan_id UUID NOT NULL REFERENCES source_scans(id) ON DELETE CASCADE,
    source_symbol_id UUID REFERENCES code_symbols(id) ON DELETE SET NULL,
    source_type business_rule_source_type NOT NULL,
    content TEXT NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_business_rules_project_scan
    ON business_rules (project_id, source_scan_id);

CREATE TABLE agent_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_scan_id UUID NOT NULL REFERENCES source_scans(id) ON DELETE RESTRICT,
    llm_config_id UUID REFERENCES llm_configs(id) ON DELETE SET NULL,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    api_definition_ids JSONB NOT NULL DEFAULT '[]'::JSONB,
    status agent_run_status NOT NULL DEFAULT 'pending',
    current_node VARCHAR(128) NOT NULL DEFAULT 'validate_input',
    prompt_version VARCHAR(64) NOT NULL,
    model_snapshot JSONB NOT NULL DEFAULT '{}'::JSONB,
    state_summary JSONB NOT NULL DEFAULT '{}'::JSONB,
    error_category agent_error_category,
    error_code VARCHAR(128),
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_agent_runs_project_created
    ON agent_runs (project_id, created_at);

CREATE TABLE agent_checkpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_run_id UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL,
    node_name VARCHAR(128) NOT NULL,
    state JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_agent_checkpoints_run_sequence UNIQUE (agent_run_id, sequence)
);

CREATE INDEX idx_agent_checkpoints_run
    ON agent_checkpoints (agent_run_id, sequence);

CREATE TABLE test_cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_scan_id UUID NOT NULL REFERENCES source_scans(id) ON DELETE RESTRICT,
    api_definition_id UUID NOT NULL REFERENCES api_definitions(id) ON DELETE RESTRICT,
    agent_run_id UUID REFERENCES agent_runs(id) ON DELETE SET NULL,
    name VARCHAR(256) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category test_case_category NOT NULL,
    priority VARCHAR(16) NOT NULL DEFAULT 'P1',
    status test_case_status NOT NULL DEFAULT 'draft',
    preconditions JSONB NOT NULL DEFAULT '[]'::JSONB,
    request_template JSONB NOT NULL DEFAULT '{}'::JSONB,
    source_rule_ids JSONB NOT NULL DEFAULT '[]'::JSONB,
    source_symbol_ids JSONB NOT NULL DEFAULT '[]'::JSONB,
    confidence DOUBLE PRECISION NOT NULL,
    is_inferred BOOLEAN NOT NULL DEFAULT FALSE,
    reviewed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX idx_test_cases_project_api
    ON test_cases (project_id, api_definition_id);
CREATE INDEX idx_test_cases_project_status
    ON test_cases (project_id, status);

CREATE TABLE test_assertions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    test_case_id UUID NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    assertion_type VARCHAR(64) NOT NULL,
    config JSONB NOT NULL DEFAULT '{}'::JSONB,
    description TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_test_assertions_case_position UNIQUE (test_case_id, position)
);

CREATE TABLE execution_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    environment_id UUID NOT NULL REFERENCES test_environments(id) ON DELETE RESTRICT,
    background_task_id UUID NOT NULL REFERENCES background_tasks(id) ON DELETE CASCADE,
    requested_by UUID REFERENCES users(id) ON DELETE SET NULL,
    status execution_run_status NOT NULL DEFAULT 'pending',
    stop_on_failure BOOLEAN NOT NULL DEFAULT FALSE,
    runtime_variables JSONB NOT NULL DEFAULT '{}'::JSONB,
    total_count INTEGER NOT NULL DEFAULT 0,
    passed_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    error_code VARCHAR(128),
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT execution_runs_background_task_id_key UNIQUE (background_task_id)
);

CREATE INDEX idx_execution_runs_project_created
    ON execution_runs (project_id, created_at);

CREATE TABLE execution_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_run_id UUID NOT NULL REFERENCES execution_runs(id) ON DELETE CASCADE,
    test_case_id UUID NOT NULL REFERENCES test_cases(id) ON DELETE RESTRICT,
    position INTEGER NOT NULL,
    status execution_step_status NOT NULL DEFAULT 'pending',
    method VARCHAR(10),
    target_url TEXT,
    request_snapshot JSONB NOT NULL DEFAULT '{}'::JSONB,
    response_snapshot JSONB NOT NULL DEFAULT '{}'::JSONB,
    redacted_curl TEXT,
    duration_ms INTEGER,
    error_category execution_error_category,
    error_code VARCHAR(128),
    error_message TEXT,
    skip_reason TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_execution_steps_run_position UNIQUE (execution_run_id, position)
);

CREATE INDEX idx_execution_steps_run_status
    ON execution_steps (execution_run_id, status, position);

CREATE TABLE assertion_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_step_id UUID NOT NULL REFERENCES execution_steps(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    assertion_type VARCHAR(64) NOT NULL,
    path TEXT,
    expected JSONB,
    actual JSONB,
    passed BOOLEAN NOT NULL,
    message TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_assertion_results_step_position UNIQUE (execution_step_id, position)
);

CREATE INDEX idx_assertion_results_step
    ON assertion_results (execution_step_id, position);

CREATE TABLE test_suites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name VARCHAR(256) NOT NULL,
    description TEXT,
    stop_on_failure BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_test_suites_project_updated
    ON test_suites (project_id, updated_at);

CREATE TABLE test_suite_steps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    test_suite_id UUID NOT NULL REFERENCES test_suites(id) ON DELETE CASCADE,
    test_case_id UUID NOT NULL REFERENCES test_cases(id) ON DELETE RESTRICT,
    position INTEGER NOT NULL,
    request_override JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_test_suite_steps_position UNIQUE (test_suite_id, position)
);

CREATE TABLE variable_extractions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    test_suite_step_id UUID NOT NULL REFERENCES test_suite_steps(id) ON DELETE CASCADE,
    variable_key VARCHAR(128) NOT NULL,
    source variable_extraction_source NOT NULL,
    expression TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_variable_extractions_step_key UNIQUE (test_suite_step_id, variable_key)
);

ALTER TABLE execution_runs
    ADD COLUMN test_suite_id UUID,
    ADD CONSTRAINT fk_execution_runs_test_suite
        FOREIGN KEY (test_suite_id) REFERENCES test_suites(id) ON DELETE SET NULL;

ALTER TABLE execution_steps
    ADD COLUMN test_suite_step_id UUID,
    ADD COLUMN request_override JSONB NOT NULL DEFAULT '{}'::JSONB,
    ADD COLUMN variable_extractions JSONB NOT NULL DEFAULT '[]'::JSONB,
    ADD COLUMN extracted_variables JSONB NOT NULL DEFAULT '{}'::JSONB,
    ADD COLUMN case_snapshot JSONB NOT NULL DEFAULT '{}'::JSONB,
    ADD COLUMN traceability_snapshot JSONB NOT NULL DEFAULT '{}'::JSONB,
    ADD CONSTRAINT fk_execution_steps_test_suite_step
        FOREIGN KEY (test_suite_step_id) REFERENCES test_suite_steps(id) ON DELETE SET NULL;

CREATE TABLE execution_diagnoses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    execution_run_id UUID NOT NULL REFERENCES execution_runs(id) ON DELETE CASCADE,
    execution_step_id UUID REFERENCES execution_steps(id) ON DELETE SET NULL,
    failure_category VARCHAR(64) NOT NULL,
    evidence_summary JSONB NOT NULL DEFAULT '{}'::JSONB,
    source_references JSONB NOT NULL DEFAULT '[]'::JSONB,
    hypotheses JSONB NOT NULL DEFAULT '[]'::JSONB,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_execution_diagnoses_run_created
    ON execution_diagnoses (execution_run_id, created_at);

CREATE TABLE alembic_version (
    version_num VARCHAR(64) NOT NULL,
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

INSERT INTO alembic_version (version_num)
VALUES ('0018_add_execution_traceability_snapshots');

COMMIT;
