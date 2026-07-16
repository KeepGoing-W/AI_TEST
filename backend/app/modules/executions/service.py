"""执行任务的创建、调度与证据保存。"""

from collections import defaultdict
from datetime import UTC, datetime
from typing import cast
from urllib.parse import urlparse
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import AppError
from app.config import get_settings
from app.modules.environments.models import EnvironmentVariable, TestEnvironment
from app.modules.executions.assertion_engine import evaluate_assertion, parse_response_json
from app.modules.executions.extractions import extract_runtime_value
from app.modules.executions.models import (
    AssertionResult,
    ExecutionErrorCategory,
    ExecutionRun,
    ExecutionRunStatus,
    ExecutionStep,
    ExecutionStepStatus,
)
from app.modules.executions.redaction import build_redacted_curl, redact_headers, redact_text, redact_value
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.runner import RunnerError, send_request, validate_execution_target
from app.modules.executions.schemas import (
    AssertionResultResponse,
    ExecutionRunResponse,
    ExecutionStartRequest,
    ExecutionStepResponse,
)
from app.modules.executions.variables import BuiltRequest, build_request
from app.modules.agents.models import AgentRun
from app.modules.knowledge.models import BusinessRule
from app.modules.source_scans.models import ApiDefinition, BackgroundTask, CodeSymbol, SourceFile, SourceScan, TaskStatus, TaskType
from app.modules.testcases.models import TestCase, TestCaseStatus
from app.modules.test_suites.models import TestSuite, VariableExtractionSource
from app.modules.test_suites.repository import TestSuiteRepository
from app.modules.users.models import User


async def create_execution_run(
    session: AsyncSession, project_id: UUID, current_user: User, payload: ExecutionStartRequest
) -> ExecutionRun:
    """只允许已审核用例进入后台执行队列。"""

    repository = ExecutionRepository(session)
    environment = await session.get(TestEnvironment, payload.environment_id)
    if environment is None or environment.project_id != project_id:
        raise AppError("ENVIRONMENT_NOT_FOUND", "测试环境不存在", 404)
    if len(set(payload.test_case_ids)) != len(payload.test_case_ids):
        raise AppError("EXECUTION_TEST_CASE_DUPLICATED", "执行用例不能重复", 400)
    test_cases = await repository.get_test_cases(project_id, payload.test_case_ids)
    if len(test_cases) != len(payload.test_case_ids):
        raise AppError("TEST_CASE_NOT_FOUND", "测试用例不存在", 404)
    if any(test_case.status != TestCaseStatus.APPROVED for test_case in test_cases):
        raise AppError("TEST_CASE_NOT_APPROVED", "仅已审核用例可以执行", 409)
    cases_by_id = {test_case.id: test_case for test_case in test_cases}
    ordered_cases = [cases_by_id[case_id] for case_id in payload.test_case_ids]
    apis = await repository.get_api_definitions([test_case.api_definition_id for test_case in ordered_cases])
    apis_by_id = {api.id: api for api in apis}
    if len(apis_by_id) != len({test_case.api_definition_id for test_case in ordered_cases}):
        raise AppError("API_DEFINITION_NOT_FOUND", "测试用例关联接口不存在", 409)
    namespaces = await load_variable_namespaces(session, environment, {})
    write_required = False
    for test_case in ordered_cases:
        api = apis_by_id[test_case.api_definition_id]
        # 先构造所有请求，变量或模板错误不会留下半成品任务。
        build_request(
            api.method,
            api.normalized_path,
            environment.base_url,
            environment.common_headers,
            test_case.request_template,
            namespaces,
        )
        write_required = write_required or api.method in {"POST", "PUT", "PATCH", "DELETE"}
    _validate_write_confirmation(environment, write_required, payload.write_confirmed, payload.confirmed_host)
    task = BackgroundTask(project_id=project_id, task_type=TaskType.EXECUTION, requested_by=current_user.id)
    session.add(task)
    await session.flush()
    run = ExecutionRun(
        project_id=project_id,
        environment_id=environment.id,
        background_task_id=task.id,
        requested_by=current_user.id,
        stop_on_failure=payload.stop_on_failure,
        total_count=len(ordered_cases),
    )
    session.add(run)
    await session.flush()
    snapshots = await _build_traceability_snapshots(session, repository, run.id, ordered_cases, apis_by_id)
    session.add_all(
        [
            ExecutionStep(
                execution_run_id=run.id,
                test_case_id=test_case.id,
                position=position,
                case_snapshot=snapshots[test_case.id][0],
                traceability_snapshot=snapshots[test_case.id][1],
            )
            for position, test_case in enumerate(ordered_cases, start=1)
        ]
    )
    task.payload = {"executionRunId": str(run.id), "writeConfirmed": payload.write_confirmed, "confirmedHost": payload.confirmed_host}
    await session.commit()
    await session.refresh(run)
    return run


async def create_suite_execution_run(
    session: AsyncSession,
    project_id: UUID,
    current_user: User,
    suite: TestSuite,
    environment_id: UUID,
    write_confirmed: bool,
    confirmed_host: str | None,
) -> ExecutionRun:
    """把流程定义复制为不可变执行步骤，运行中不再读取可变的流程配置。"""

    repository = ExecutionRepository(session)
    environment = await session.get(TestEnvironment, environment_id)
    if environment is None or environment.project_id != project_id:
        raise AppError("ENVIRONMENT_NOT_FOUND", "测试环境不存在", 404)
    suite_repository = TestSuiteRepository(session)
    suite_steps = await suite_repository.list_steps(suite.id)
    test_cases = await repository.get_test_cases(project_id, [step.test_case_id for step in suite_steps])
    if len(test_cases) != len({step.test_case_id for step in suite_steps}) or any(case.status != TestCaseStatus.APPROVED for case in test_cases):
        raise AppError("TEST_CASE_NOT_APPROVED", "流程引用的用例不存在或未审核", 409)
    cases_by_id = {case.id: case for case in test_cases}
    api_definitions = await repository.get_api_definitions([case.api_definition_id for case in test_cases])
    apis_by_id = {api.id: api for api in api_definitions}
    if len(apis_by_id) != len({test_case.api_definition_id for test_case in test_cases}):
        raise AppError("API_DEFINITION_NOT_FOUND", "测试用例关联接口不存在", 409)
    extractions_by_step: dict[UUID, list[object]] = defaultdict(list)
    produced_keys: set[str] = set()
    for extraction in await suite_repository.list_extractions([step.id for step in suite_steps]):
        extractions_by_step[extraction.test_suite_step_id].append(
            {"variableKey": extraction.variable_key, "source": extraction.source.value, "expression": extraction.expression}
        )
        produced_keys.add(extraction.variable_key)
    namespaces = await load_variable_namespaces(session, environment, {key: "__flow_precheck__" for key in produced_keys})
    write_required = False
    for suite_step in suite_steps:
        test_case = cases_by_id[suite_step.test_case_id]
        api = apis_by_id[test_case.api_definition_id]
        build_request(api.method, api.normalized_path, environment.base_url, environment.common_headers, _merge_request_template(test_case.request_template, suite_step.request_override), namespaces)
        write_required = write_required or api.method in {"POST", "PUT", "PATCH", "DELETE"}
    _validate_write_confirmation(environment, write_required, write_confirmed, confirmed_host)
    task = BackgroundTask(project_id=project_id, task_type=TaskType.EXECUTION, requested_by=current_user.id)
    session.add(task)
    await session.flush()
    run = ExecutionRun(project_id=project_id, test_suite_id=suite.id, environment_id=environment.id, background_task_id=task.id, requested_by=current_user.id, stop_on_failure=suite.stop_on_failure, total_count=len(suite_steps))
    session.add(run)
    await session.flush()
    snapshots = await _build_traceability_snapshots(session, repository, run.id, test_cases, apis_by_id)
    session.add_all(
        [
            ExecutionStep(
                execution_run_id=run.id,
                test_case_id=suite_step.test_case_id,
                test_suite_step_id=suite_step.id,
                position=suite_step.position,
                case_snapshot=snapshots[suite_step.test_case_id][0],
                traceability_snapshot=snapshots[suite_step.test_case_id][1],
                request_override=suite_step.request_override,
                variable_extractions=extractions_by_step[suite_step.id],
            )
            for suite_step in suite_steps
        ]
    )
    task.payload = {"executionRunId": str(run.id), "writeConfirmed": write_confirmed, "confirmedHost": confirmed_host}
    await session.commit()
    await session.refresh(run)
    return run


async def process_execution_task(session: AsyncSession, task: BackgroundTask) -> None:
    """单进程按用例顺序执行，停止策略才能精确标记后续步骤。"""

    repository = ExecutionRepository(session)
    run = await repository.get_run_by_task_id(task.id)
    if run is None:
        task.status = TaskStatus.FAILED
        task.error_code = "EXECUTION_RUN_NOT_FOUND"
        task.error_message = "执行任务不存在"
        await session.commit()
        return
    environment = await session.get(TestEnvironment, run.environment_id)
    if environment is None:
        await _fail_run(session, task, run, "ENVIRONMENT_NOT_FOUND", "测试环境不存在")
        return
    task.status = TaskStatus.RUNNING
    task.started_at = datetime.now(UTC)
    run.status = ExecutionRunStatus.RUNNING
    run.started_at = datetime.now(UTC)
    await session.commit()

    try:
        for step in await repository.list_steps(run.id):
            await session.refresh(task)
            if task.status == TaskStatus.CANCELLED:
                await _stop_remaining_steps(session, run, "用户停止执行")
                run.status = ExecutionRunStatus.STOPPED
                run.completed_at = datetime.now(UTC)
                await session.commit()
                return
            await _process_step(session, task, run, environment, step)
            await session.refresh(run)
            if run.stop_on_failure and step.status in {ExecutionStepStatus.FAILED, ExecutionStepStatus.ERROR}:
                await _skip_remaining_steps(session, run, step.position, "前序用例失败，已按停止策略跳过")
                break
        await session.refresh(task)
        if task.status != TaskStatus.CANCELLED:
            task.status = TaskStatus.SUCCEEDED
            task.completed_at = datetime.now(UTC)
            run.status = ExecutionRunStatus.COMPLETED
            run.completed_at = datetime.now(UTC)
            await session.commit()
    except Exception:
        await _fail_run(session, task, run, "EXECUTION_TASK_FAILED", "执行任务发生内部错误")
        raise


async def request_execution_stop(session: AsyncSession, project_id: UUID, run_id: UUID) -> ExecutionRun:
    """待领取任务直接终止；运行中的任务在当前请求完成后停止。"""

    repository = ExecutionRepository(session)
    run = await repository.get_run(project_id, run_id)
    if run is None:
        raise AppError("EXECUTION_RUN_NOT_FOUND", "执行任务不存在", 404)
    if run.status not in {ExecutionRunStatus.PENDING, ExecutionRunStatus.RUNNING}:
        raise AppError("EXECUTION_STOP_NOT_AVAILABLE", "当前执行任务不能停止", 409)
    task = await repository.get_background_task(run.background_task_id)
    if task is None:
        raise AppError("EXECUTION_TASK_NOT_FOUND", "后台任务不存在", 409)
    task.status = TaskStatus.CANCELLED
    if run.status == ExecutionRunStatus.PENDING:
        await _stop_remaining_steps(session, run, "用户停止执行")
        run.status = ExecutionRunStatus.STOPPED
        run.completed_at = datetime.now(UTC)
        task.completed_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(run)
    return run


async def retry_failed_execution(
    session: AsyncSession,
    project_id: UUID,
    current_user: User,
    previous_run_id: UUID,
    write_confirmed: bool,
    confirmed_host: str | None,
) -> ExecutionRun:
    """失败重试只复制失败或网络错误用例，不复制运行变量。"""

    repository = ExecutionRepository(session)
    previous = await repository.get_run(project_id, previous_run_id)
    if previous is None:
        raise AppError("EXECUTION_RUN_NOT_FOUND", "执行任务不存在", 404)
    retry_ids = [
        step.test_case_id
        for step in await repository.list_steps(previous.id)
        if step.status in {ExecutionStepStatus.FAILED, ExecutionStepStatus.ERROR}
    ]
    if not retry_ids:
        raise AppError("EXECUTION_RETRY_NOT_AVAILABLE", "没有可重新执行的失败用例", 409)
    return await create_execution_run(
        session,
        project_id,
        current_user,
        ExecutionStartRequest(
            environment_id=previous.environment_id,
            test_case_ids=retry_ids,
            stop_on_failure=previous.stop_on_failure,
            write_confirmed=write_confirmed,
            confirmed_host=confirmed_host,
        ),
    )


async def get_execution_response(session: AsyncSession, project_id: UUID, run_id: UUID) -> ExecutionRunResponse:
    repository = ExecutionRepository(session)
    run = await repository.get_run(project_id, run_id)
    if run is None:
        raise AppError("EXECUTION_RUN_NOT_FOUND", "执行任务不存在", 404)
    steps = await repository.list_steps(run.id)
    results_by_step: dict[UUID, list[AssertionResultResponse]] = defaultdict(list)
    for result in await repository.list_results([step.id for step in steps]):
        results_by_step[result.execution_step_id].append(
            AssertionResultResponse(
                id=result.id,
                position=result.position,
                assertion_type=result.assertion_type,
                path=result.path,
                expected=result.expected,
                actual=result.actual,
                passed=result.passed,
                message=result.message,
            )
        )
    return ExecutionRunResponse(
        id=run.id,
        project_id=run.project_id,
        test_suite_id=run.test_suite_id,
        environment_id=run.environment_id,
        background_task_id=run.background_task_id,
        status=run.status,
        stop_on_failure=run.stop_on_failure,
        total_count=run.total_count,
        passed_count=run.passed_count,
        failed_count=run.failed_count,
        skipped_count=run.skipped_count,
        error_code=run.error_code,
        error_message=run.error_message,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
        steps=[
            ExecutionStepResponse(
                id=step.id,
                test_case_id=step.test_case_id,
                position=step.position,
                status=step.status,
                method=step.method,
                target_url=step.target_url,
                request_snapshot=step.request_snapshot,
                case_snapshot=step.case_snapshot,
                traceability_snapshot=step.traceability_snapshot,
                request_override=step.request_override,
                variable_extractions=step.variable_extractions,
                extracted_variables=step.extracted_variables,
                response_snapshot=step.response_snapshot,
                redacted_curl=step.redacted_curl,
                duration_ms=step.duration_ms,
                error_category=step.error_category,
                error_code=step.error_code,
                error_message=step.error_message,
                skip_reason=step.skip_reason,
                assertions=results_by_step[step.id],
                started_at=step.started_at,
                completed_at=step.completed_at,
            )
            for step in steps
        ],
    )


async def load_variable_namespaces(
    session: AsyncSession, environment: TestEnvironment, runtime_variables: dict[str, object]
) -> dict[str, dict[str, object]]:
    """密钥仅在内存中解密，用于请求构造前的变量解析。"""

    variables = list(
        await session.scalars(select(EnvironmentVariable).where(EnvironmentVariable.environment_id == environment.id))
    )
    env_values: dict[str, object] = {"baseUrl": environment.base_url}
    secret_values: dict[str, object] = {}
    for variable in variables:
        if variable.is_secret:
            secret_values[variable.variable_key] = _decrypt_variable(variable)
        elif variable.value is not None:
            env_values[variable.variable_key] = variable.value
    return {"env": env_values, "secret": secret_values, "runtime": runtime_variables}


async def _process_step(
    session: AsyncSession,
    task: BackgroundTask,
    run: ExecutionRun,
    environment: TestEnvironment,
    step: ExecutionStep,
) -> None:
    repository = ExecutionRepository(session)
    step.status = ExecutionStepStatus.RUNNING
    step.started_at = datetime.now(UTC)
    await session.commit()
    test_case = (await repository.get_test_cases(run.project_id, [step.test_case_id]))[0]
    api = (await repository.get_api_definitions([test_case.api_definition_id]))[0]
    try:
        namespaces = await load_variable_namespaces(session, environment, run.runtime_variables)
        request = build_request(
            api.method,
            api.normalized_path,
            environment.base_url,
            environment.common_headers,
            _merge_request_template(test_case.request_template, step.request_override),
            namespaces,
        )
        step.method = request.method
        step.target_url = request.url
        step.request_snapshot = _request_snapshot(request)
        step.redacted_curl = build_redacted_curl(request)
        target = await validate_execution_target(
            environment,
            request,
            bool(task.payload.get("writeConfirmed", False)),
            _as_string_or_none(task.payload.get("confirmedHost")),
        )
        response = await send_request(request, get_settings(), target)
        step.duration_ms = response.duration_ms
        body_json = parse_response_json(response.body_text)
        step.response_snapshot = {
            "statusCode": response.status_code,
            "headers": redact_headers(response.headers),
            "body": redact_value(body_json) if body_json is not None else redact_text(response.body_text),
        }
        evaluations = [
            evaluate_assertion(
                assertion.assertion_type,
                assertion.config,
                response.status_code,
                response.body_text,
                body_json,
                response.duration_ms,
            )
            for assertion in await repository.get_assertions(test_case.id)
        ]
        session.add_all(
            [
                AssertionResult(
                    execution_step_id=step.id,
                    position=position,
                    assertion_type=evaluation.assertion_type,
                    path=evaluation.path,
                    expected=cast(object, redact_value(evaluation.expected)),
                    actual=cast(object, redact_value(evaluation.actual)),
                    passed=evaluation.passed,
                    message=evaluation.message,
                )
                for position, evaluation in enumerate(evaluations, start=1)
            ]
        )
        extracted = _extract_step_variables(step, body_json, response.body_text, response.headers, response.status_code)
        # 真实运行变量只保存在该执行记录内；步骤证据仅保存经过字段名脱敏后的副本。
        run.runtime_variables = run.runtime_variables | extracted
        step.extracted_variables = redact_value(extracted)
        if all(evaluation.passed for evaluation in evaluations):
            step.status = ExecutionStepStatus.PASSED
            run.passed_count += 1
        else:
            step.status = ExecutionStepStatus.FAILED
            step.error_category = ExecutionErrorCategory.ASSERTION
            step.error_code = "ASSERTION_FAILED"
            step.error_message = "存在未通过断言"
            run.failed_count += 1
    except RunnerError as exc:
        await _record_step_error(step, run, exc.category, exc.code, exc.message)
    except AppError as exc:
        category = ExecutionErrorCategory.VARIABLE_EXTRACTION if exc.code == "VARIABLE_EXTRACTION_FAILED" else ExecutionErrorCategory.PRECONDITION if exc.code == "EXECUTION_VARIABLE_MISSING" else ExecutionErrorCategory.REQUEST_BUILD
        await _record_step_error(step, run, category, exc.code, exc.message)
    except Exception:
        await _record_step_error(step, run, ExecutionErrorCategory.INTERNAL, "EXECUTION_STEP_FAILED", "执行用例时发生内部错误")
    step.completed_at = datetime.now(UTC)
    await session.commit()


async def _record_step_error(
    step: ExecutionStep,
    run: ExecutionRun,
    category: ExecutionErrorCategory,
    code: str,
    message: str,
) -> None:
    step.status = ExecutionStepStatus.ERROR
    step.error_category = category
    step.error_code = code
    step.error_message = message
    run.failed_count += 1


async def _skip_remaining_steps(session: AsyncSession, run: ExecutionRun, position: int, reason: str) -> None:
    for step in await ExecutionRepository(session).list_steps(run.id):
        if step.position > position and step.status == ExecutionStepStatus.PENDING:
            step.status = ExecutionStepStatus.SKIPPED
            step.skip_reason = reason
            step.completed_at = datetime.now(UTC)
            run.skipped_count += 1
    await session.commit()


async def _stop_remaining_steps(session: AsyncSession, run: ExecutionRun, reason: str) -> None:
    for step in await ExecutionRepository(session).list_steps(run.id):
        if step.status == ExecutionStepStatus.PENDING:
            step.status = ExecutionStepStatus.STOPPED
            step.skip_reason = reason
            step.completed_at = datetime.now(UTC)
            run.skipped_count += 1
    await session.flush()


async def _fail_run(session: AsyncSession, task: BackgroundTask, run: ExecutionRun, code: str, message: str) -> None:
    task.status = TaskStatus.FAILED
    task.error_code = code
    task.error_message = message
    task.completed_at = datetime.now(UTC)
    run.status = ExecutionRunStatus.FAILED
    run.error_code = code
    run.error_message = message
    run.completed_at = datetime.now(UTC)
    await session.commit()


def _validate_write_confirmation(
    environment: TestEnvironment, write_required: bool, write_confirmed: bool, confirmed_host: str | None
) -> None:
    if environment.environment_type.value == "production":
        raise AppError("EXECUTION_PRODUCTION_FORBIDDEN", "生产环境禁止执行", 403)
    if not write_required:
        return
    expected_host = _environment_host(environment.base_url)
    if not environment.allow_write_requests:
        raise AppError("EXECUTION_WRITE_FORBIDDEN", "当前环境禁止写请求", 403)
    if not write_confirmed or confirmed_host != expected_host:
        raise AppError("EXECUTION_WRITE_CONFIRMATION_REQUIRED", "写请求需要确认当前目标 Host", 409)


def _environment_host(base_url: str) -> str:
    try:
        parsed = urlparse(base_url)
        _ = parsed.port
    except ValueError as exc:
        raise AppError("ENVIRONMENT_BASE_URL_INVALID", "测试环境 Base URL 无效", 400) from exc
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AppError("ENVIRONMENT_BASE_URL_INVALID", "测试环境 Base URL 无效", 400)
    return f"{parsed.scheme}://{parsed.netloc}"


def _decrypt_variable(variable: EnvironmentVariable) -> str:
    if variable.encrypted_value is None:
        raise AppError("ENVIRONMENT_SECRET_INVALID", "加密变量未配置", 409)
    try:
        return Fernet(get_settings().encryption_key.get_secret_value()).decrypt(variable.encrypted_value.encode()).decode()
    except (InvalidToken, ValueError, TypeError) as exc:
        raise AppError("ENVIRONMENT_SECRET_INVALID", "加密变量无法读取", 500) from exc


def _request_snapshot(request: BuiltRequest) -> dict[str, object]:
    return {
        "method": request.method,
        "url": request.url,
        "query": redact_value(request.query),
        "headers": redact_headers(request.headers),
        "body": redact_value(request.json_body) if request.json_body is not None else redact_text(request.text_body or ""),
    }


def _as_string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


async def _build_traceability_snapshots(
    session: AsyncSession,
    repository: ExecutionRepository,
    run_id: UUID,
    test_cases: list[TestCase],
    apis_by_id: dict[UUID, ApiDefinition],
) -> dict[UUID, tuple[dict[str, object], dict[str, object]]]:
    """在入队时固化用例版本及其 Agent、规则、符号和扫描版本证据。"""

    rule_ids = {UUID(str(rule_id)) for case in test_cases for rule_id in case.source_rule_ids}
    symbol_ids = {UUID(str(symbol_id)) for case in test_cases for symbol_id in case.source_symbol_ids}
    scan_ids = {case.source_scan_id for case in test_cases}
    agent_run_ids = {case.agent_run_id for case in test_cases if case.agent_run_id is not None}
    rules = {
        rule.id: rule
        for rule in await session.scalars(select(BusinessRule).where(BusinessRule.id.in_(rule_ids)))
    } if rule_ids else {}
    symbols = {
        symbol.id: symbol
        for symbol in await session.scalars(select(CodeSymbol).where(CodeSymbol.id.in_(symbol_ids)))
    } if symbol_ids else {}
    source_files = {
        source_file.id: source_file
        for source_file in await session.scalars(
            select(SourceFile).where(SourceFile.id.in_({symbol.source_file_id for symbol in symbols.values()}))
        )
    } if symbols else {}
    scans = {
        scan.id: scan
        for scan in await session.scalars(select(SourceScan).where(SourceScan.id.in_(scan_ids)))
    }
    agent_runs = {
        agent_run.id: agent_run
        for agent_run in await session.scalars(select(AgentRun).where(AgentRun.id.in_(agent_run_ids)))
    } if agent_run_ids else {}
    assertions_by_case = {
        case.id: await repository.get_assertions(case.id)
        for case in test_cases
    }
    snapshots: dict[UUID, tuple[dict[str, object], dict[str, object]]] = {}
    for case in test_cases:
        api = apis_by_id[case.api_definition_id]
        scan = scans.get(case.source_scan_id)
        agent_run = agent_runs.get(case.agent_run_id) if case.agent_run_id is not None else None
        case_snapshot = {
            "id": str(case.id),
            "version": case.version,
            "name": case.name,
            "category": case.category.value,
            "status": case.status.value,
            "api": {"id": str(case.api_definition_id), "method": api.method, "path": api.normalized_path},
            "preconditions": case.preconditions,
            "requestTemplate": redact_value(case.request_template),
            "assertions": [
                {
                    "position": assertion.position,
                    "type": assertion.assertion_type,
                    "config": redact_value(assertion.config),
                }
                for assertion in assertions_by_case[case.id]
            ],
        }
        traceability_snapshot = {
            "executionRunId": str(run_id),
            "testCase": {"id": str(case.id), "version": case.version},
            "sourceScan": {"id": str(case.source_scan_id), "version": scan.scan_version if scan is not None else None},
            "businessRules": [
                {
                    "id": str(rule.id),
                    "sourceType": rule.source_type.value,
                    "sourceSymbolId": str(rule.source_symbol_id) if rule.source_symbol_id is not None else None,
                }
                for rule_id in case.source_rule_ids
                if (rule := rules.get(UUID(str(rule_id)))) is not None
            ],
            "sourceSymbols": [
                {
                    "id": str(symbol.id),
                    "qualifiedName": symbol.qualified_name,
                    "sourceFilePath": source_files[symbol.source_file_id].relative_path
                    if symbol.source_file_id in source_files
                    else None,
                    "startLine": symbol.start_line,
                    "endLine": symbol.end_line,
                }
                for symbol_id in case.source_symbol_ids
                if (symbol := symbols.get(UUID(str(symbol_id)))) is not None
            ],
            "agentRun": None
            if agent_run is None
            else {
                "id": str(agent_run.id),
                "promptVersion": agent_run.prompt_version,
                "modelSnapshot": agent_run.model_snapshot,
            },
        }
        snapshots[case.id] = (case_snapshot, traceability_snapshot)
    return snapshots


def _merge_request_template(template: dict[str, object], override: dict[str, object]) -> dict[str, object]:
    """流程覆盖只合并固定请求区段，原用例仍是流程执行的稳定基线。"""

    merged = dict(template)
    for section, value in override.items():
        if section in {"path", "query", "headers", "body"} and isinstance(value, dict) and isinstance(merged.get(section), dict):
            merged[section] = dict(cast(dict[str, object], merged[section])) | value
        else:
            merged[section] = value
    return merged


def _extract_step_variables(
    step: ExecutionStep, body_json: object | None, body_text: str, headers: dict[str, str], status_code: int
) -> dict[str, object]:
    """按照创建时冻结的提取规则写入运行变量，提取失败会阻断该步骤的最终通过状态。"""

    values: dict[str, object] = {}
    for raw_rule in step.variable_extractions:
        if not isinstance(raw_rule, dict):
            raise AppError("VARIABLE_EXTRACTION_FAILED", "变量提取规则无效", 409)
        key, source = raw_rule.get("variableKey"), raw_rule.get("source")
        expression = raw_rule.get("expression")
        if not isinstance(key, str) or not isinstance(source, str) or not (expression is None or isinstance(expression, str)):
            raise AppError("VARIABLE_EXTRACTION_FAILED", "变量提取规则无效", 409)
        try:
            extraction_source = VariableExtractionSource(source)
        except ValueError as exc:
            raise AppError("VARIABLE_EXTRACTION_FAILED", "变量提取方式无效", 409) from exc
        values[key] = extract_runtime_value(extraction_source, expression, body_json, body_text, headers, status_code)
    return values
