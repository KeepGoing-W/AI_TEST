from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.source_scans.models import (
    ApiDefinition,
    BackgroundTask,
    CodeSymbol,
    SourceFile,
    SourceScan,
    SymbolRelation,
    TaskStatus,
)


class SourceScanRepository:
    """源码扫描与后台任务数据访问。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lock_project_and_get_next_version(self, project_id: UUID) -> int:
        await self.session.execute(select(Project).where(Project.id == project_id).with_for_update())
        latest_version = await self.session.scalar(
            select(func.max(SourceScan.scan_version)).where(SourceScan.project_id == project_id)
        )
        return (latest_version or 0) + 1

    async def get_scan(self, project_id: UUID, scan_id: UUID) -> SourceScan | None:
        return await self.session.scalar(
            select(SourceScan).where(SourceScan.project_id == project_id, SourceScan.id == scan_id)
        )

    async def get_scan_by_task_id(self, task_id: UUID) -> SourceScan | None:
        return await self.session.scalar(select(SourceScan).where(SourceScan.background_task_id == task_id))

    async def list_scans(self, project_id: UUID) -> list[SourceScan]:
        result = await self.session.scalars(
            select(SourceScan).where(SourceScan.project_id == project_id).order_by(SourceScan.scan_version.desc())
        )
        return list(result)

    async def list_api_definitions(
        self, project_id: UUID, source_scan_id: UUID
    ) -> list[ApiDefinition]:
        result = await self.session.scalars(
            select(ApiDefinition)
            .where(ApiDefinition.project_id == project_id, ApiDefinition.source_scan_id == source_scan_id)
            .order_by(ApiDefinition.normalized_path, ApiDefinition.method)
        )
        return list(result)

    async def get_api_definition(
        self, project_id: UUID, source_scan_id: UUID, api_definition_id: UUID
    ) -> ApiDefinition | None:
        return await self.session.scalar(
            select(ApiDefinition).where(
                ApiDefinition.project_id == project_id,
                ApiDefinition.source_scan_id == source_scan_id,
                ApiDefinition.id == api_definition_id,
            )
        )

    def add_source_files(self, source_files: list[SourceFile]) -> None:
        self.session.add_all(source_files)

    def add_code_symbols(self, code_symbols: list[CodeSymbol]) -> None:
        self.session.add_all(code_symbols)

    def add_api_definitions(self, api_definitions: list[ApiDefinition]) -> None:
        self.session.add_all(api_definitions)

    def add_symbol_relations(self, symbol_relations: list[SymbolRelation]) -> None:
        self.session.add_all(symbol_relations)

    async def claim_next_task(self) -> BackgroundTask | None:
        statement = (
            select(BackgroundTask)
            .where(BackgroundTask.status == TaskStatus.PENDING)
            .order_by(BackgroundTask.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        return await self.session.scalar(statement)
