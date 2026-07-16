from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.test_suites.models import TestSuite, TestSuiteStep, VariableExtraction


class TestSuiteRepository:
    """流程聚合的查询统一收敛，避免 Router 操作 ORM。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_suite(self, project_id: UUID, suite_id: UUID) -> TestSuite | None:
        return await self.session.scalar(select(TestSuite).where(TestSuite.project_id == project_id, TestSuite.id == suite_id))

    async def list_suites(self, project_id: UUID) -> list[TestSuite]:
        return list(await self.session.scalars(select(TestSuite).where(TestSuite.project_id == project_id).order_by(TestSuite.updated_at.desc())))

    async def list_steps(self, suite_id: UUID) -> list[TestSuiteStep]:
        return list(await self.session.scalars(select(TestSuiteStep).where(TestSuiteStep.test_suite_id == suite_id).order_by(TestSuiteStep.position)))

    async def list_extractions(self, step_ids: list[UUID]) -> list[VariableExtraction]:
        if not step_ids:
            return []
        return list(await self.session.scalars(select(VariableExtraction).where(VariableExtraction.test_suite_step_id.in_(step_ids))))
