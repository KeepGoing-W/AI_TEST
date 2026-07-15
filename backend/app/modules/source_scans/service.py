from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import AppError
from app.modules.projects.repository import ProjectRepository
from app.modules.source_scans.models import ApiDefinition, BackgroundTask, CodeSymbol, ScanStatus, SourceFile, SourceScan, TaskStatus, TaskType
from app.modules.source_scans.repository import SourceScanRepository
from app.modules.source_scans.schemas import ApiDefinitionResponse


async def serialize_api_definition(session: AsyncSession, api_definition: ApiDefinition) -> dict[str, object]:
    """补全接口定义的来源符号，供扫描版本查询复用。"""

    controller = (
        await session.get(CodeSymbol, api_definition.controller_symbol_id)
        if api_definition.controller_symbol_id is not None
        else None
    )
    method = await session.get(CodeSymbol, api_definition.method_symbol_id) if api_definition.method_symbol_id is not None else None
    source_file = await session.get(SourceFile, method.source_file_id) if method is not None else None
    return ApiDefinitionResponse(
        id=api_definition.id,
        source_scan_id=api_definition.source_scan_id,
        method=api_definition.method,
        normalized_path=api_definition.normalized_path,
        operation_id=api_definition.operation_id,
        source_file_path=source_file.relative_path if source_file is not None else None,
        controller_qualified_name=controller.qualified_name if controller is not None else None,
        method_qualified_name=method.qualified_name if method is not None else None,
        request_definition=api_definition.request_definition,
        response_definition=api_definition.response_definition,
        security_definition=api_definition.security_definition,
        source_definition=api_definition.source_definition,
        openapi_definition=api_definition.openapi_definition,
        conflicts=api_definition.conflicts,
        is_conflicted=api_definition.is_conflicted,
    ).model_dump(mode="json")


async def list_source_scan_api_definitions(
    session: AsyncSession, project_id: UUID, scan_id: UUID
) -> list[dict[str, object]]:
    repository = SourceScanRepository(session)
    if await repository.get_scan(project_id, scan_id) is None:
        raise AppError("SOURCE_SCAN_NOT_FOUND", "扫描任务不存在", 404)
    definitions = await repository.list_api_definitions(project_id, scan_id)
    return [await serialize_api_definition(session, definition) for definition in definitions]


async def get_source_scan_api_definition(
    session: AsyncSession, project_id: UUID, scan_id: UUID, api_definition_id: UUID
) -> dict[str, object]:
    definition = await SourceScanRepository(session).get_api_definition(project_id, scan_id, api_definition_id)
    if definition is None:
        raise AppError("API_DEFINITION_NOT_FOUND", "接口定义不存在", 404)
    return await serialize_api_definition(session, definition)


async def create_source_scan(session: AsyncSession, project_id: UUID, user_id: UUID) -> SourceScan:
    """为项目创建待执行的独立扫描版本。"""

    artifact = await ProjectRepository(session).get_source_artifact(project_id)
    if artifact is None:
        raise AppError("SOURCE_ARTIFACT_NOT_CONFIGURED", "项目尚未配置源码来源", 409)

    repository = SourceScanRepository(session)
    scan_version = await repository.lock_project_and_get_next_version(project_id)
    task = BackgroundTask(project_id=project_id, task_type=TaskType.SOURCE_SCAN, requested_by=user_id)
    session.add(task)
    await session.flush()
    scan = SourceScan(
        project_id=project_id,
        source_artifact_id=artifact.id,
        background_task_id=task.id,
        scan_version=scan_version,
        created_by=user_id,
    )
    session.add(scan)
    await session.commit()
    await session.refresh(scan)
    return scan


async def mark_scan_running(session: AsyncSession, task: BackgroundTask, scan: SourceScan) -> None:
    """将已领取扫描任务切换至执行中。"""

    task.status = TaskStatus.RUNNING
    task.result = {"progress": 10, "phase": "queued"}
    scan.status = ScanStatus.RUNNING
    await session.flush()


async def mark_scan_succeeded(
    session: AsyncSession, task: BackgroundTask, scan: SourceScan, summary: dict[str, object]
) -> None:
    """记录完成的扫描任务摘要。"""

    task.status = TaskStatus.SUCCEEDED
    task.result = {"progress": 100, "phase": "completed"}
    scan.status = ScanStatus.SUCCEEDED
    scan.summary = summary
    await session.flush()


async def mark_scan_failed(
    session: AsyncSession,
    task: BackgroundTask,
    scan: SourceScan,
    error_code: str,
    error_message: str,
) -> None:
    """记录可恢复的扫描任务失败状态。"""

    task.status = TaskStatus.FAILED
    task.error_code = error_code
    task.error_message = error_message
    scan.status = ScanStatus.FAILED
    scan.error_code = error_code
    scan.error_message = error_message
    await session.flush()
