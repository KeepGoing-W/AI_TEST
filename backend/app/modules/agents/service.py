"""Agent 运行编排、错误归类与服务重启恢复策略。"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import AppError
from app.modules.agents.graph import TestGenerationGraph, TestGenerationState
from app.modules.agents.llm import AgentLlmClient, AgentLlmError, model_snapshot, resolve_llm_config
from app.modules.agents.models import AgentErrorCategory, AgentRun, AgentRunStatus
from app.modules.agents.repository import AgentRepository
from app.modules.agents.schemas import PROMPT_VERSION, ReviewRequest, TestcaseGenerationRequest
from app.modules.agents.tools import AgentTools
from app.modules.source_scans.repository import SourceScanRepository
from app.modules.testcases.models import TestCaseStatus
from app.modules.users.models import User


async def create_testcase_generation_run(
    session: AsyncSession,
    project_id: UUID,
    current_user: User,
    payload: TestcaseGenerationRequest,
) -> AgentRun:
    """创建并同步执行一条受控 Agent 运行，结束时停在人工审核边界。"""

    if await SourceScanRepository(session).get_scan(project_id, payload.source_scan_id) is None:
        raise AppError("SOURCE_SCAN_NOT_FOUND", "扫描任务不存在", 404)
    llm_config = await resolve_llm_config(session, payload.llm_config_id)
    run = AgentRun(
        project_id=project_id,
        source_scan_id=payload.source_scan_id,
        llm_config_id=llm_config.id,
        created_by=current_user.id,
        api_definition_ids=[str(api_id) for api_id in payload.api_definition_ids],
        status=AgentRunStatus.RUNNING,
        current_node="validate_input",
        prompt_version=PROMPT_VERSION,
        model_snapshot=model_snapshot(llm_config),
        started_at=datetime.now(UTC),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    tools = AgentTools(session, current_user.id, current_user.role)
    graph = TestGenerationGraph(run, tools, AgentLlmClient(llm_config)).compile()
    initial_state: TestGenerationState = {
        "project_id": str(project_id),
        "source_scan_id": str(payload.source_scan_id),
        "run_id": str(run.id),
        "api_definition_ids": [str(api_id) for api_id in payload.api_definition_ids],
        "api_definitions": [],
        "retrieved_context": {},
        "confirmed_rules": [],
        "business_rules": [],
        "persisted_rule_ids": [],
        "scenarios": [],
        "generated_cases": [],
        "persisted_case_ids": [],
        "validation_errors": [],
        "review_status": "draft",
        "model_snapshot": run.model_snapshot,
    }
    try:
        # LangGraph 会在 human_review_interrupt 前返回，草稿已转为 pending_review。
        await graph.ainvoke(initial_state)
        await session.refresh(run)
        if run.status != AgentRunStatus.PENDING_REVIEW:
            raise AppError("AGENT_RUN_INTERRUPTED", "Agent 未进入人工审核状态", 500)
        run.completed_at = datetime.now(UTC)
        await session.commit()
        return run
    except AgentLlmError as exc:
        await _mark_failed(session, run, _error_category_for_llm(exc), exc.code, exc.message, exc.raw_preview)
        raise AppError(exc.code, exc.message, 422) from exc
    except AppError as exc:
        await _mark_failed(session, run, _error_category_for_app_error(exc), exc.code, exc.message)
        raise
    except Exception as exc:
        await _mark_failed(session, run, AgentErrorCategory.RECOVERY, "AGENT_RUN_FAILED", "Agent 运行失败")
        raise AppError("AGENT_RUN_FAILED", "Agent 运行失败", 500) from exc


async def review_agent_run(
    session: AsyncSession,
    project_id: UUID,
    run_id: UUID,
    reviewer: User,
    payload: ReviewRequest,
) -> AgentRun:
    """按人工决定完成 pending_review 到 approved 或 disabled 的不可逆状态迁移。"""

    run = await AgentRepository(session).get_run(project_id, run_id)
    if run is None:
        raise AppError("AGENT_RUN_NOT_FOUND", "Agent 运行不存在", 404)
    if run.status != AgentRunStatus.PENDING_REVIEW:
        raise AppError("AGENT_REVIEW_NOT_AVAILABLE", "当前运行不在待审核状态", 409)
    cases = await AgentRepository(session).list_test_cases(project_id, run_id)
    if not cases:
        raise AppError("TEST_CASE_NOT_FOUND", "当前运行没有待审核用例", 409)
    target_status = TestCaseStatus.APPROVED if payload.status == "approved" else TestCaseStatus.DISABLED
    for case in cases:
        if case.status != TestCaseStatus.PENDING_REVIEW:
            raise AppError("TEST_CASE_REVIEW_STATE_INVALID", "存在非待审核用例，无法批量审核", 409)
        case.status = target_status
        case.reviewed_by = reviewer.id
        case.version += 1
    run.status = AgentRunStatus.APPROVED if payload.status == "approved" else AgentRunStatus.DISABLED
    run.current_node = "human_review_interrupt"
    run.completed_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(run)
    return run


async def fail_interrupted_agent_runs(session: AsyncSession) -> int:
    """服务启动时明确失败未完成运行，避免假装可从内存中恢复。"""

    runs = list(await session.scalars(select(AgentRun).where(AgentRun.status == AgentRunStatus.RUNNING)))
    for run in runs:
        run.status = AgentRunStatus.FAILED
        run.error_category = AgentErrorCategory.RECOVERY
        run.error_code = "AGENT_RUN_INTERRUPTED"
        run.error_message = "服务重启导致 Agent 运行中断，请重新发起分析"
        run.completed_at = datetime.now(UTC)
    if runs:
        await session.commit()
    return len(runs)


async def _mark_failed(
    session: AsyncSession,
    run: AgentRun,
    category: AgentErrorCategory,
    code: str,
    message: str,
    raw_output_preview: str = "",
) -> None:
    """保存稳定错误码、分类与有限诊断摘要，不写入密钥或完整模型输出。"""

    run.status = AgentRunStatus.FAILED
    run.error_category = category
    run.error_code = code
    run.error_message = message
    run.completed_at = datetime.now(UTC)
    if raw_output_preview:
        run.state_summary = run.state_summary | {"rawOutputPreview": raw_output_preview}
    await session.commit()


def _error_category_for_llm(error: AgentLlmError) -> AgentErrorCategory:
    """将模型调用错误和结构化输出错误映射为稳定错误分类。"""

    return AgentErrorCategory.OUTPUT if error.code == "AGENT_OUTPUT_INVALID" else AgentErrorCategory.MODEL


def _error_category_for_app_error(error: AppError) -> AgentErrorCategory:
    """项目、扫描和检索边界错误分别反映为输入或检索问题。"""

    if error.code in {"API_DEFINITION_NOT_FOUND", "SOURCE_SCAN_NOT_FOUND"}:
        return AgentErrorCategory.RETRIEVAL
    return AgentErrorCategory.INPUT
