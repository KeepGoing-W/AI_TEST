from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.modules.source_scans.models import ScanStatus, TaskStatus


class SourceScanResponse(BaseModel):
    """扫描任务响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    background_task_id: UUID
    scan_version: int
    status: ScanStatus
    summary: dict[str, object]
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime


class ScanProgressEvent(BaseModel):
    """扫描进度 SSE 数据。"""

    task_id: UUID
    scan_id: UUID
    scan_version: int
    task_status: TaskStatus
    scan_status: ScanStatus
    progress: int
    phase: str
    error_code: str | None


class ApiDefinitionResponse(BaseModel):
    """扫描版本中已发现的接口定义。"""

    id: UUID
    source_scan_id: UUID
    method: str
    normalized_path: str
    operation_id: str | None
    source_file_path: str | None
    controller_qualified_name: str | None
    method_qualified_name: str | None
    request_definition: dict[str, object]
    response_definition: dict[str, object]
    security_definition: dict[str, object]
    source_definition: dict[str, object]
    openapi_definition: dict[str, object]
    conflicts: list[object]
    is_conflicted: bool
