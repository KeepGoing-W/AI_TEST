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
from app.modules.source_scans.models import BackgroundTask, TaskStatus, TaskType
from app.modules.testcases.models import TestCase, TestCaseStatus
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
    if len(apis_by_id) != len(ordered_cases):
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
    session.add_all(
        [
            ExecutionStep(execution_run_id=run.id, test_case_id=test_case.id, position=position)
            for position, test_case in enumerate(ordered_cases, start=1)
        ]
    )
    task.payload = {"executionRunId": str(run.id), "writeConfirmed": payload.write_confirmed, "confirmedHost": payload.confirmed_host}
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
            test_case.request_template,
            namespaces,
        )
        step.method = request.method
        step.target_url = request.url
        step.request_snapshot = _request_snapshot(request)
        step.redacted_curl = build_redacted_curl(request)
        await validate_execution_target(
            environment,
            request,
            bool(task.payload.get("writeConfirmed", False)),
            _as_string_or_none(task.payload.get("confirmedHost")),
        )
        response = await send_request(request, get_settings())
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
        await _record_step_error(step, run, ExecutionErrorCategory.REQUEST_BUILD, exc.code, exc.message)
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
    parsed = urlparse(base_url)
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
