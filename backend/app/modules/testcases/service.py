"""M4 用例查询、人工编辑与审核前保护逻辑。"""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import AppError
from app.modules.agents.repository import AgentRepository
from app.modules.agents.schemas import TestAssertionResponse, TestCaseResponse, TestCaseUpdateRequest
from app.modules.testcases.models import TestAssertion, TestCase, TestCaseStatus
from app.modules.source_scans.models import ApiDefinition


async def list_test_cases(
    session: AsyncSession, project_id: UUID, agent_run_id: UUID | None, api_definition_id: UUID | None
) -> list[TestCaseResponse]:
    """返回项目内用例并附带顺序稳定的断言列表。"""

    cases = await AgentRepository(session).list_test_cases(project_id, agent_run_id)
    if api_definition_id is not None:
        cases = [case for case in cases if case.api_definition_id == api_definition_id]
    assertions = await AgentRepository(session).list_assertions([case.id for case in cases])
    apis = (
        list(
            await session.scalars(
                select(ApiDefinition).where(ApiDefinition.id.in_([case.api_definition_id for case in cases]))
            )
        )
        if cases
        else []
    )
    return _serialize_cases(cases, assertions, {api.id: api for api in apis})


async def update_test_case(
    session: AsyncSession, project_id: UUID, case_id: UUID, payload: TestCaseUpdateRequest
) -> TestCaseResponse:
    """只允许在审核前修改可编辑字段，不允许编辑生成来源和审核状态。"""

    cases = await AgentRepository(session).list_test_cases(project_id)
    test_case = next((case for case in cases if case.id == case_id), None)
    if test_case is None:
        raise AppError("TEST_CASE_NOT_FOUND", "测试用例不存在", 404)
    if test_case.status not in {TestCaseStatus.DRAFT, TestCaseStatus.PENDING_REVIEW}:
        raise AppError("TEST_CASE_EDIT_NOT_AVAILABLE", "已审核或已禁用用例不能编辑", 409)
    for field_name in ("name", "description", "priority", "preconditions", "request_template"):
        value = getattr(payload, field_name)
        if value is not None:
            setattr(test_case, field_name, value)
    if payload.assertions is not None:
        old_assertions = await AgentRepository(session).list_assertions([test_case.id])
        for assertion in old_assertions:
            await session.delete(assertion)
        await session.flush()
        session.add_all(
            [
                TestAssertion(
                    test_case_id=test_case.id,
                    position=position,
                    assertion_type=assertion.assertion_type,
                    config=assertion.config,
                    description=assertion.description,
                )
                for position, assertion in enumerate(payload.assertions, start=1)
            ]
        )
    test_case.version += 1
    await session.commit()
    await session.refresh(test_case)
    assertions = await AgentRepository(session).list_assertions([test_case.id])
    api = await session.get(ApiDefinition, test_case.api_definition_id)
    if api is None:
        raise AppError("API_DEFINITION_NOT_FOUND", "测试用例关联接口不存在", 409)
    return _serialize_cases([test_case], assertions, {api.id: api})[0]


def _serialize_cases(
    cases: list[TestCase], assertions: list[TestAssertion], apis_by_id: dict[UUID, ApiDefinition]
) -> list[TestCaseResponse]:
    """集中转换 ORM 实体，保持 Router 不承载组装逻辑。"""

    assertions_by_case: dict[UUID, list[TestAssertionResponse]] = defaultdict(list)
    for assertion in assertions:
        assertions_by_case[assertion.test_case_id].append(
            TestAssertionResponse(
                id=assertion.id,
                position=assertion.position,
                assertion_type=assertion.assertion_type,
                config=assertion.config,
                description=assertion.description,
            )
        )
    serialized: list[TestCaseResponse] = []
    for case in cases:
        api = apis_by_id.get(case.api_definition_id)
        if api is None:
            continue
        serialized.append(
            TestCaseResponse(
                id=case.id,
                project_id=case.project_id,
                source_scan_id=case.source_scan_id,
                api_definition_id=case.api_definition_id,
                api_method=api.method,
                api_path=api.normalized_path,
                agent_run_id=case.agent_run_id,
                name=case.name,
                description=case.description,
                category=case.category,
                priority=case.priority,
                status=case.status,
                version=case.version,
                preconditions=[str(value) for value in case.preconditions],
                request_template=case.request_template,
                source_rule_ids=[UUID(str(value)) for value in case.source_rule_ids],
                source_symbol_ids=[UUID(str(value)) for value in case.source_symbol_ids],
                confidence=case.confidence,
                is_inferred=case.is_inferred,
                assertions=assertions_by_case[case.id],
                created_at=case.created_at,
                updated_at=case.updated_at,
            )
        )
    return serialized
