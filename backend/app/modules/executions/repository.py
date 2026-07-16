from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.executions.models import AssertionResult, ExecutionRun, ExecutionStep
from app.modules.source_scans.models import ApiDefinition, BackgroundTask
from app.modules.testcases.models import TestAssertion, TestCase


class ExecutionRepository:
    """执行记录读写集中在此处，Router 不直接操作 ORM。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_run(self, project_id: UUID, run_id: UUID) -> ExecutionRun | None:
        return await self.session.scalar(
            select(ExecutionRun).where(ExecutionRun.project_id == project_id, ExecutionRun.id == run_id)
        )

    async def get_run_by_task_id(self, task_id: UUID) -> ExecutionRun | None:
        return await self.session.scalar(select(ExecutionRun).where(ExecutionRun.background_task_id == task_id))

    async def list_runs(self, project_id: UUID) -> list[ExecutionRun]:
        return list(
            await self.session.scalars(
                select(ExecutionRun).where(ExecutionRun.project_id == project_id).order_by(ExecutionRun.created_at.desc())
            )
        )

    async def list_steps(self, run_id: UUID) -> list[ExecutionStep]:
        return list(
            await self.session.scalars(
                select(ExecutionStep).where(ExecutionStep.execution_run_id == run_id).order_by(ExecutionStep.position)
            )
        )

    async def list_results(self, step_ids: list[UUID]) -> list[AssertionResult]:
        if not step_ids:
            return []
        return list(
            await self.session.scalars(
                select(AssertionResult)
                .where(AssertionResult.execution_step_id.in_(step_ids))
                .order_by(AssertionResult.execution_step_id, AssertionResult.position)
            )
        )

    async def get_test_cases(self, project_id: UUID, case_ids: list[UUID]) -> list[TestCase]:
        if not case_ids:
            return []
        return list(
            await self.session.scalars(
                select(TestCase).where(TestCase.project_id == project_id, TestCase.id.in_(case_ids))
            )
        )

    async def get_api_definitions(self, api_ids: list[UUID]) -> list[ApiDefinition]:
        if not api_ids:
            return []
        return list(await self.session.scalars(select(ApiDefinition).where(ApiDefinition.id.in_(api_ids))))

    async def get_assertions(self, case_id: UUID) -> list[TestAssertion]:
        return list(
            await self.session.scalars(
                select(TestAssertion).where(TestAssertion.test_case_id == case_id).order_by(TestAssertion.position)
            )
        )

    async def get_background_task(self, task_id: UUID) -> BackgroundTask | None:
        return await self.session.get(BackgroundTask, task_id)
