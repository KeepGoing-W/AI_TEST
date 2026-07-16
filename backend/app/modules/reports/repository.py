from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.executions.models import ExecutionRun
from app.modules.reports.models import ExecutionDiagnosis


class ReportRepository:
    """报告和诊断持久化查询。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_runs(self, project_id: UUID) -> list[ExecutionRun]:
        return list(await self.session.scalars(select(ExecutionRun).where(ExecutionRun.project_id == project_id).order_by(ExecutionRun.created_at.desc())))

    async def get_diagnosis(self, project_id: UUID, diagnosis_id: UUID) -> ExecutionDiagnosis | None:
        return await self.session.scalar(select(ExecutionDiagnosis).join(ExecutionRun).where(ExecutionRun.project_id == project_id, ExecutionDiagnosis.id == diagnosis_id))

    async def list_diagnoses(self, run_id: UUID) -> list[ExecutionDiagnosis]:
        return list(await self.session.scalars(select(ExecutionDiagnosis).where(ExecutionDiagnosis.execution_run_id == run_id).order_by(ExecutionDiagnosis.created_at.desc())))
