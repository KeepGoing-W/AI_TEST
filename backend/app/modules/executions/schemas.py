from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.executions.models import ExecutionErrorCategory, ExecutionRunStatus, ExecutionStepStatus


class ExecutionStartRequest(BaseModel):
    """创建执行任务；写请求必须在当前请求中再次确认。"""

    environment_id: UUID
    test_case_ids: list[UUID] = Field(min_length=1, max_length=100)
    stop_on_failure: bool = False
    write_confirmed: bool = False
    confirmed_host: str | None = Field(default=None, max_length=2048)


class ExecutionRetryRequest(BaseModel):
    """重新执行失败用例仍需重复写请求确认。"""

    write_confirmed: bool = False
    confirmed_host: str | None = Field(default=None, max_length=2048)


class AssertionResultResponse(BaseModel):
    id: UUID
    position: int
    assertion_type: str
    path: str | None
    expected: object | None
    actual: object | None
    passed: bool
    message: str


class ExecutionStepResponse(BaseModel):
    id: UUID
    test_case_id: UUID
    position: int
    status: ExecutionStepStatus
    method: str | None
    target_url: str | None
    request_snapshot: dict[str, object]
    case_snapshot: dict[str, object]
    traceability_snapshot: dict[str, object]
    request_override: dict[str, object]
    variable_extractions: list[object]
    extracted_variables: dict[str, object]
    response_snapshot: dict[str, object]
    redacted_curl: str | None
    duration_ms: int | None
    error_category: ExecutionErrorCategory | None
    error_code: str | None
    error_message: str | None
    skip_reason: str | None
    assertions: list[AssertionResultResponse]
    started_at: datetime | None
    completed_at: datetime | None


class ExecutionRunResponse(BaseModel):
    id: UUID
    project_id: UUID
    test_suite_id: UUID | None
    environment_id: UUID
    background_task_id: UUID
    status: ExecutionRunStatus
    stop_on_failure: bool
    total_count: int
    passed_count: int
    failed_count: int
    skipped_count: int
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    steps: list[ExecutionStepResponse] = Field(default_factory=list)


class ExecutionProgressEvent(BaseModel):
    """SSE 仅传递进度与终态，不暴露请求正文。"""

    run_id: UUID
    status: ExecutionRunStatus
    total_count: int
    passed_count: int
    failed_count: int
    skipped_count: int
    current_step_id: UUID | None


AssertionType = Literal[
    "status_code_equals",
    "business_code_equals",
    "json_path_equals",
    "json_path_exists",
    "json_path_not_exists",
    "json_path_type",
    "body_contains",
    "body_not_contains",
    "number_range",
    "response_time_less_than",
]
