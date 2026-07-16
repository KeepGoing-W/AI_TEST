from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.executions.schemas import ExecutionRunResponse


class ReportCounter(BaseModel):
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0


class ReportDimension(BaseModel):
    key: str
    label: str
    counter: ReportCounter


class FailureReason(BaseModel):
    category: str
    code: str
    count: int


class ExecutionReportResponse(BaseModel):
    run_id: UUID
    test_suite_id: UUID | None
    status: str
    pass_rate: float
    summary: ReportCounter
    categories: list[ReportDimension]
    apis: list[ReportDimension]
    failure_reasons: list[FailureReason]
    execution: ExecutionRunResponse


class ExecutionReportListItem(BaseModel):
    run_id: UUID
    test_suite_id: UUID | None
    status: str
    pass_rate: float
    summary: ReportCounter
    created_at: datetime


class DiagnosisResponse(BaseModel):
    id: UUID
    execution_run_id: UUID
    execution_step_id: UUID | None
    failure_category: str
    evidence_summary: dict[str, object]
    source_references: list[object]
    hypotheses: list[object]
    note: str | None
    created_at: datetime
