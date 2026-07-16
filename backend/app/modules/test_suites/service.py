from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import AppError
from app.modules.executions.models import ExecutionRun
from app.modules.executions.service import create_suite_execution_run
from app.modules.executions.variables import find_runtime_variables
from app.modules.test_suites.models import TestSuite, TestSuiteStep, VariableExtraction
from app.modules.test_suites.repository import TestSuiteRepository
from app.modules.test_suites.schemas import (
    TestSuiteCreateRequest,
    TestSuiteResponse,
    TestSuiteStepResponse,
    TestSuiteUpdateRequest,
    VariableExtractionResponse,
)
from app.modules.testcases.models import TestCase, TestCaseStatus
from app.modules.users.models import User


async def create_test_suite(session: AsyncSession, project_id: UUID, current_user: User, payload: TestSuiteCreateRequest) -> TestSuite:
    suite = TestSuite(project_id=project_id, name=payload.name.strip(), description=payload.description, stop_on_failure=payload.stop_on_failure, created_by=current_user.id)
    session.add(suite)
    await session.flush()
    await _replace_steps(session, project_id, suite, payload)
    await session.commit()
    await session.refresh(suite)
    return suite


async def update_test_suite(session: AsyncSession, project_id: UUID, suite_id: UUID, payload: TestSuiteUpdateRequest) -> TestSuite:
    suite = await TestSuiteRepository(session).get_suite(project_id, suite_id)
    if suite is None:
        raise AppError("TEST_SUITE_NOT_FOUND", "测试流程不存在", 404)
    suite.name, suite.description, suite.stop_on_failure = payload.name.strip(), payload.description, payload.stop_on_failure
    for step in await TestSuiteRepository(session).list_steps(suite.id):
        await session.delete(step)
    await session.flush()
    await _replace_steps(session, project_id, suite, payload)
    await session.commit()
    await session.refresh(suite)
    return suite


async def list_test_suite_responses(session: AsyncSession, project_id: UUID) -> list[TestSuiteResponse]:
    return [await get_test_suite_response(session, project_id, suite.id) for suite in await TestSuiteRepository(session).list_suites(project_id)]


async def get_test_suite_response(session: AsyncSession, project_id: UUID, suite_id: UUID) -> TestSuiteResponse:
    repository = TestSuiteRepository(session)
    suite = await repository.get_suite(project_id, suite_id)
    if suite is None:
        raise AppError("TEST_SUITE_NOT_FOUND", "测试流程不存在", 404)
    steps = await repository.list_steps(suite.id)
    extractions_by_step: dict[UUID, list[VariableExtractionResponse]] = defaultdict(list)
    for extraction in await repository.list_extractions([step.id for step in steps]):
        extractions_by_step[extraction.test_suite_step_id].append(VariableExtractionResponse(id=extraction.id, variable_key=extraction.variable_key, source=extraction.source, expression=extraction.expression))
    return TestSuiteResponse(id=suite.id, project_id=suite.project_id, name=suite.name, description=suite.description, stop_on_failure=suite.stop_on_failure, created_at=suite.created_at, updated_at=suite.updated_at, steps=[TestSuiteStepResponse(id=step.id, test_case_id=step.test_case_id, position=step.position, request_override=step.request_override, variable_extractions=extractions_by_step[step.id]) for step in steps])


async def start_test_suite_run(
    session: AsyncSession,
    project_id: UUID,
    suite_id: UUID,
    current_user: User,
    environment_id: UUID,
    write_confirmed: bool,
    confirmed_host: str | None,
) -> ExecutionRun:
    suite = await TestSuiteRepository(session).get_suite(project_id, suite_id)
    if suite is None:
        raise AppError("TEST_SUITE_NOT_FOUND", "测试流程不存在", 404)
    return await create_suite_execution_run(session, project_id, current_user, suite, environment_id, write_confirmed, confirmed_host)


async def _replace_steps(session: AsyncSession, project_id: UUID, suite: TestSuite, payload: TestSuiteCreateRequest) -> None:
    case_ids = [step.test_case_id for step in payload.steps]
    cases = list(await session.scalars(select(TestCase).where(TestCase.project_id == project_id, TestCase.id.in_(set(case_ids)))))
    if len(cases) != len(set(case_ids)):
        raise AppError("TEST_CASE_NOT_FOUND", "测试用例不存在", 404)
    if any(case.status != TestCaseStatus.APPROVED for case in cases):
        raise AppError("TEST_CASE_NOT_APPROVED", "流程仅能引用已审核用例", 409)
    cases_by_id = {case.id: case for case in cases}
    produced: set[str] = set()
    for position, item in enumerate(payload.steps, start=1):
        invalid_sections = set(item.request_override) - {"path", "query", "headers", "body", "auth"}
        if invalid_sections:
            raise AppError("TEST_SUITE_REQUEST_OVERRIDE_INVALID", "请求覆盖包含不支持的区段", 400)
        template = _merge_template(cases_by_id[item.test_case_id].request_template, item.request_override)
        missing = find_runtime_variables(template) - produced
        if missing:
            raise AppError("TEST_SUITE_VARIABLE_PRODUCER_MISSING", f"第 {position} 步引用了尚未生产的变量：{', '.join(sorted(missing))}", 400)
        keys = [extraction.variable_key for extraction in item.variable_extractions]
        if len(set(keys)) != len(keys) or set(keys) & produced:
            raise AppError("TEST_SUITE_VARIABLE_DUPLICATED", "运行变量只能由一个上游步骤生产", 400)
        step = TestSuiteStep(test_suite_id=suite.id, test_case_id=item.test_case_id, position=position, request_override=item.request_override)
        session.add(step)
        await session.flush()
        session.add_all([VariableExtraction(test_suite_step_id=step.id, variable_key=extraction.variable_key, source=extraction.source, expression=extraction.expression) for extraction in item.variable_extractions])
        produced.update(keys)


def _merge_template(template: dict[str, object], override: dict[str, object]) -> dict[str, object]:
    """请求覆盖仅覆盖同名区段内字段，避免流程配置意外抹掉原用例请求。"""
    merged = dict(template)
    for section, value in override.items():
        if section in {"path", "query", "headers", "body"} and isinstance(value, dict) and isinstance(merged.get(section), dict):
            merged[section] = dict(merged[section]) | value
        else:
            merged[section] = value
    return merged
