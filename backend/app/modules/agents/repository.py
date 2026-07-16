from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agents.models import AgentCheckpoint, AgentRun
from app.modules.knowledge.models import BusinessRule, BusinessRuleSourceType
from app.modules.source_scans.models import ApiDefinition, CodeSymbol, SymbolRelation
from app.modules.testcases.models import TestAssertion, TestCase


class AgentRepository:
    """Agent 运行及其受控读取所需的数据访问。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_run(self, project_id: UUID, run_id: UUID) -> AgentRun | None:
        return await self.session.scalar(select(AgentRun).where(AgentRun.project_id == project_id, AgentRun.id == run_id))

    async def list_checkpoints(self, run_id: UUID) -> list[AgentCheckpoint]:
        values = await self.session.scalars(
            select(AgentCheckpoint).where(AgentCheckpoint.agent_run_id == run_id).order_by(AgentCheckpoint.sequence)
        )
        return list(values)

    async def get_api_definitions(
        self, project_id: UUID, source_scan_id: UUID, api_ids: list[UUID]
    ) -> list[ApiDefinition]:
        values = await self.session.scalars(
            select(ApiDefinition).where(
                ApiDefinition.project_id == project_id,
                ApiDefinition.source_scan_id == source_scan_id,
                ApiDefinition.id.in_(api_ids),
            )
        )
        return list(values)

    async def get_symbols(self, source_scan_id: UUID, symbol_ids: list[UUID]) -> list[CodeSymbol]:
        if not symbol_ids:
            return []
        values = await self.session.scalars(
            select(CodeSymbol).where(CodeSymbol.source_scan_id == source_scan_id, CodeSymbol.id.in_(symbol_ids))
        )
        return list(values)

    async def list_child_symbols(self, source_scan_id: UUID, parent_symbol_ids: set[UUID]) -> list[CodeSymbol]:
        """读取已限定 DTO 的字段子符号，不能按名称跨扫描版本检索。"""

        if not parent_symbol_ids:
            return []
        values = await self.session.scalars(
            select(CodeSymbol).where(
                CodeSymbol.source_scan_id == source_scan_id,
                CodeSymbol.parent_symbol_id.in_(parent_symbol_ids),
            )
        )
        return list(values)

    async def list_symbol_relations(self, source_scan_id: UUID, symbol_ids: list[UUID]) -> list[SymbolRelation]:
        if not symbol_ids:
            return []
        values = await self.session.scalars(
            select(SymbolRelation).where(
                SymbolRelation.source_scan_id == source_scan_id,
                SymbolRelation.source_symbol_id.in_(symbol_ids),
            )
        )
        return list(values)

    async def list_confirmed_rules(self, project_id: UUID, source_scan_id: UUID) -> list[BusinessRule]:
        values = await self.session.scalars(
            select(BusinessRule).where(
                BusinessRule.project_id == project_id,
                BusinessRule.source_scan_id == source_scan_id,
                BusinessRule.source_type == BusinessRuleSourceType.SOURCE_CONFIRMED,
            )
        )
        return list(values)

    async def list_test_cases(self, project_id: UUID, agent_run_id: UUID | None = None) -> list[TestCase]:
        statement = select(TestCase).where(TestCase.project_id == project_id).order_by(TestCase.created_at.desc())
        if agent_run_id is not None:
            statement = statement.where(TestCase.agent_run_id == agent_run_id)
        return list(await self.session.scalars(statement))

    async def list_assertions(self, test_case_ids: list[UUID]) -> list[TestAssertion]:
        if not test_case_ids:
            return []
        return list(
            await self.session.scalars(
                select(TestAssertion)
                .where(TestAssertion.test_case_id.in_(test_case_ids))
                .order_by(TestAssertion.test_case_id, TestAssertion.position)
            )
        )
