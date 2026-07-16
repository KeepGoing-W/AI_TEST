from collections import Counter, defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import AppError
from app.modules.executions.models import ExecutionRun, ExecutionStepStatus
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.schemas import ExecutionRetryRequest
from app.modules.executions.service import create_suite_execution_run, get_execution_response, retry_failed_execution
from app.modules.reports.diagnostic_graph import DiagnosticState, FailureDiagnosticGraph
from app.modules.reports.models import ExecutionDiagnosis
from app.modules.reports.repository import ReportRepository
from app.modules.reports.schemas import (
    DiagnosisResponse,
    ExecutionReportListItem,
    ExecutionReportResponse,
    FailureReason,
    ReportCounter,
    ReportDimension,
)
from app.modules.source_scans.models import CodeSymbol
from app.modules.test_suites.models import TestSuite
from app.modules.users.models import User


async def get_report(session: AsyncSession, project_id: UUID, run_id: UUID) -> ExecutionReportResponse:
    execution = await get_execution_response(session, project_id, run_id)
    case_ids = [step.test_case_id for step in execution.steps]
    repository = ExecutionRepository(session)
    cases = await repository.get_test_cases(project_id, case_ids)
    cases_by_id = {case.id: case for case in cases}
    apis = await repository.get_api_definitions([case.api_definition_id for case in cases])
    apis_by_id = {api.id: api for api in apis}
    category_counters: dict[str, ReportCounter] = defaultdict(ReportCounter)
    api_counters: dict[str, ReportCounter] = defaultdict(ReportCounter)
    failure_reasons: Counter[tuple[str, str]] = Counter()
    for step in execution.steps:
        case = cases_by_id.get(step.test_case_id)
        if case is None:
            continue
        _increment_counter(category_counters[case.category.value], step.status.value)
        api = apis_by_id.get(case.api_definition_id)
        if api is not None:
            _increment_counter(api_counters[f"{api.method} {api.normalized_path}"], step.status.value)
        if step.status in {ExecutionStepStatus.FAILED, ExecutionStepStatus.ERROR}:
            failure_reasons[((step.error_category.value if step.error_category else "execution"), step.error_code or "UNKNOWN")] += 1
    summary = ReportCounter(total=execution.total_count, passed=execution.passed_count, failed=execution.failed_count, skipped=execution.skipped_count)
    return ExecutionReportResponse(run_id=execution.id, test_suite_id=execution.test_suite_id, status=execution.status.value, pass_rate=round(execution.passed_count / execution.total_count, 4) if execution.total_count else 0, summary=summary, categories=[ReportDimension(key=key, label=key, counter=value) for key, value in sorted(category_counters.items())], apis=[ReportDimension(key=key, label=key, counter=value) for key, value in sorted(api_counters.items())], failure_reasons=[FailureReason(category=category, code=code, count=count) for (category, code), count in failure_reasons.most_common()], execution=execution)


async def list_report_items(session: AsyncSession, project_id: UUID) -> list[ExecutionReportListItem]:
    reports: list[ExecutionReportListItem] = []
    for run in await ReportRepository(session).list_runs(project_id):
        report = await get_report(session, project_id, run.id)
        reports.append(ExecutionReportListItem(run_id=report.run_id, test_suite_id=report.test_suite_id, status=report.status, pass_rate=report.pass_rate, summary=report.summary, created_at=run.created_at))
    return reports


async def retry_report_execution(
    session: AsyncSession,
    project_id: UUID,
    run_id: UUID,
    current_user: User,
    payload: ExecutionRetryRequest,
) -> ExecutionRun:
    run = await ExecutionRepository(session).get_run(project_id, run_id)
    if run is None:
        raise AppError("EXECUTION_RUN_NOT_FOUND", "执行任务不存在", 404)
    if run.test_suite_id is None:
        return await retry_failed_execution(session, project_id, current_user, run_id, payload.write_confirmed, payload.confirmed_host)
    suite = await session.get(TestSuite, run.test_suite_id)
    if suite is None:
        raise AppError("TEST_SUITE_NOT_FOUND", "原测试流程不存在", 409)
    # 流程重试必须从第一步重放，才能重新建立 Token、ID 等下游依赖变量。
    return await create_suite_execution_run(session, project_id, current_user, suite, run.environment_id, payload.write_confirmed, payload.confirmed_host)


async def create_failure_diagnoses(session: AsyncSession, project_id: UUID, run_id: UUID, current_user: User) -> list[DiagnosisResponse]:
    execution = await get_execution_response(session, project_id, run_id)
    failed_steps = [step for step in execution.steps if step.status in {ExecutionStepStatus.FAILED, ExecutionStepStatus.ERROR}]
    if not failed_steps:
        raise AppError("DIAGNOSIS_NOT_AVAILABLE", "当前执行没有可诊断的失败步骤", 409)
    repository = ExecutionRepository(session)
    stored_steps = {step.id: step for step in await repository.list_steps(run_id)}
    cases = {case.id: case for case in await repository.get_test_cases(project_id, [step.test_case_id for step in failed_steps])}
    apis = {api.id: api for api in await repository.get_api_definitions([case.api_definition_id for case in cases.values()])}
    diagnoses: list[ExecutionDiagnosis] = []
    for step_response in failed_steps:
        stored = stored_steps[step_response.id]
        api = apis.get(cases[step_response.test_case_id].api_definition_id)
        symbol_ids = [value for value in (api.controller_symbol_id, api.method_symbol_id) if value is not None] if api else []
        symbols = list(await session.scalars(select(CodeSymbol).where(CodeSymbol.id.in_(symbol_ids)))) if symbol_ids else []
        graph = FailureDiagnosticGraph(stored, api, symbols).compile()
        state: DiagnosticState = await graph.ainvoke({"category": "", "evidence": {}, "source_references": [], "hypotheses": []})
        diagnosis = ExecutionDiagnosis(execution_run_id=run_id, execution_step_id=stored.id, failure_category=state["category"], evidence_summary=state["evidence"], source_references=state["source_references"], hypotheses=state["hypotheses"], created_by=current_user.id, note="诊断仅提供原因假设，不影响执行结果")
        session.add(diagnosis)
        diagnoses.append(diagnosis)
    await session.commit()
    for diagnosis in diagnoses:
        await session.refresh(diagnosis)
    return [_diagnosis_response(item) for item in diagnoses]


def _increment_counter(counter: ReportCounter, status: str) -> None:
    counter.total += 1
    if status == "passed":
        counter.passed += 1
    elif status in {"failed", "error"}:
        counter.failed += 1
    elif status in {"skipped", "stopped"}:
        counter.skipped += 1


def _diagnosis_response(item: ExecutionDiagnosis) -> DiagnosisResponse:
    return DiagnosisResponse(id=item.id, execution_run_id=item.execution_run_id, execution_step_id=item.execution_step_id, failure_category=item.failure_category, evidence_summary=item.evidence_summary, source_references=item.source_references, hypotheses=item.hypotheses, note=item.note, created_at=item.created_at)
