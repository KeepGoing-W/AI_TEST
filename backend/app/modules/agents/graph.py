"""M4 测试用例生成 LangGraph：检索、分析、场景、结构化用例与人工审核边界。"""

import json
from typing import NotRequired, Protocol, TypedDict, cast
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.common.errors import AppError
from app.modules.agents.llm import AgentLlmClient
from app.modules.agents.models import AgentRun, AgentRunStatus
from app.modules.agents.schemas import (
    BusinessRuleDraft,
    PROMPT_VERSION,
    StructuredCaseDraft,
    TestScenarioDraft,
)
from app.modules.agents.tools import (
    AgentTools,
    MarkDraftsPendingReviewInput,
    ReadApiDefinitionsInput,
    ReadConfirmedRulesInput,
    SaveAnalysisDraftInput,
    SaveCaseDraftInput,
    SearchContextInput,
    ToolApiDefinition,
)
from app.modules.knowledge.models import BusinessRuleSourceType
from app.modules.testcases.models import TestCaseCategory


class TestGenerationState(TypedDict):
    """LangGraph 状态只保留结构化结果与引用，不累积任意消息历史。"""

    project_id: str
    source_scan_id: str
    run_id: str
    api_definition_ids: list[str]
    api_definitions: list[dict[str, object]]
    retrieved_context: dict[str, dict[str, object]]
    confirmed_rules: list[dict[str, object]]
    business_rules: list[dict[str, object]]
    persisted_rule_ids: list[str]
    scenarios: list[dict[str, object]]
    generated_cases: list[dict[str, object]]
    persisted_case_ids: list[str]
    validation_errors: list[str]
    review_status: str
    model_snapshot: dict[str, object]
    raw_output_preview: NotRequired[str]


class CompiledAgentGraph(Protocol):
    """Service 需要的最小 LangGraph 可执行接口，避免泄漏第三方内部泛型。"""

    async def ainvoke(self, input: TestGenerationState) -> dict[str, object]: ...


class RuleListOutput(BaseModel):
    """规则分析节点的模型输出包装。"""

    rules: list[BusinessRuleDraft] = Field(min_length=1, max_length=100)


class ScenarioListOutput(BaseModel):
    """场景生成节点的模型输出包装。"""

    scenarios: list[TestScenarioDraft] = Field(min_length=1, max_length=100)


class CaseListOutput(BaseModel):
    """结构化用例节点的模型输出包装。"""

    cases: list[StructuredCaseDraft] = Field(min_length=1, max_length=100)


SYSTEM_PROMPT = """你是受控 API 测试分析 Agent。只能依据输入的接口定义、源码上下文和已确认规则输出 JSON。
不得编造接口、字段、状态码、业务规则或外部事实。源码事实使用 source_confirmed，无法由来源直接证明的结论
必须使用 inferred 且 confidence 不得高于 0.6。不要输出 Markdown、解释、密钥或完整源码。"""


class TestGenerationGraph:
    """把 M4 节点实现为可追踪的 LangGraph，并在每个节点后保存自有检查点。"""

    def __init__(self, run: AgentRun, tools: AgentTools, llm: AgentLlmClient) -> None:
        self.run = run
        self.tools = tools
        self.llm = llm

    def compile(self) -> CompiledAgentGraph:
        """构建并编译图；人工审核节点是 LangGraph 原生中断边界。"""

        graph = StateGraph(TestGenerationState)
        graph.add_node("validate_input", self.validate_input)
        graph.add_node("load_api_definition", self.load_api_definition)
        graph.add_node("retrieve_code_context", self.retrieve_code_context)
        graph.add_node("analyze_business_rules", self.analyze_business_rules)
        graph.add_node("generate_test_scenarios", self.generate_test_scenarios)
        graph.add_node("generate_structured_cases", self.generate_structured_cases)
        graph.add_node("validate_generated_cases", self.validate_generated_cases)
        graph.add_node("persist_drafts", self.persist_drafts)
        graph.add_node("human_review_interrupt", self.human_review_interrupt)
        graph.add_edge(START, "validate_input")
        graph.add_edge("validate_input", "load_api_definition")
        graph.add_edge("load_api_definition", "retrieve_code_context")
        graph.add_edge("retrieve_code_context", "analyze_business_rules")
        graph.add_edge("analyze_business_rules", "generate_test_scenarios")
        graph.add_edge("generate_test_scenarios", "generate_structured_cases")
        graph.add_edge("generate_structured_cases", "validate_generated_cases")
        graph.add_edge("validate_generated_cases", "persist_drafts")
        graph.add_edge("persist_drafts", "human_review_interrupt")
        graph.add_edge("human_review_interrupt", END)
        # 图会在进入此节点前暂停；草稿与检查点此前已提交，重启后可安全由审核接口继续。
        return cast(CompiledAgentGraph, graph.compile(interrupt_before=["human_review_interrupt"]))

    async def validate_input(self, state: TestGenerationState) -> dict[str, object]:
        """验证 UUID、扫描版本和至少一个接口的基本输入。"""

        if not state["api_definition_ids"]:
            raise AppError("AGENT_INPUT_INVALID", "至少需要选择一个接口", 422)
        updates = {"validation_errors": [], "review_status": "draft"}
        await self._checkpoint("validate_input", state, updates)
        return updates

    async def load_api_definition(self, state: TestGenerationState) -> dict[str, object]:
        """通过受控 Tool 加载接口与字段白名单，不直接查询任意项目数据。"""

        result = await self.tools.read_api_definitions(
            ReadApiDefinitionsInput(
                project_id=UUID(state["project_id"]),
                source_scan_id=UUID(state["source_scan_id"]),
                api_definition_ids=[UUID(api_id) for api_id in state["api_definition_ids"]],
            )
        )
        updates = {"api_definitions": [item.model_dump(mode="json") for item in result.api_definitions]}
        await self._checkpoint("load_api_definition", state, updates)
        return updates

    async def retrieve_code_context(self, state: TestGenerationState) -> dict[str, object]:
        """按接口检索源码上下文，并一并读取已确认规则作为稳定知识输入。"""

        scope = {"project_id": UUID(state["project_id"]), "source_scan_id": UUID(state["source_scan_id"])}
        contexts = await self.tools.search_context(
            SearchContextInput(
                **scope,
                api_definition_ids=[UUID(api_id) for api_id in state["api_definition_ids"]],
            )
        )
        confirmed = await self.tools.read_confirmed_rules(ReadConfirmedRulesInput(**scope))
        updates = {
            "retrieved_context": contexts.contexts,
            "confirmed_rules": [rule.model_dump(mode="json") for rule in confirmed.rules],
        }
        await self._checkpoint("retrieve_code_context", state, updates)
        return updates

    async def analyze_business_rules(self, state: TestGenerationState) -> dict[str, object]:
        """让模型提取规则，并验证每条源码确认规则均可回指本次检索来源。"""

        output = await self.llm.complete_structured(
            SYSTEM_PROMPT,
            "请基于下列资料提取业务规则。返回 {\"rules\": [...]}。\n"
            + _json_payload(
                {
                    "apiDefinitions": state["api_definitions"],
                    "contexts": state["retrieved_context"],
                    "confirmedRules": state["confirmed_rules"],
                    "promptVersion": PROMPT_VERSION,
                }
            ),
            RuleListOutput,
            lambda value: self._validate_rules(state, value),
        )
        updates = {"business_rules": [rule.model_dump(mode="json") for rule in output.rules]}
        await self._checkpoint("analyze_business_rules", state, updates)
        return updates

    async def generate_test_scenarios(self, state: TestGenerationState) -> dict[str, object]:
        """为每个接口生成四类可追溯场景；此节点不生成请求内容。"""

        output = await self.llm.complete_structured(
            SYSTEM_PROMPT,
            "请仅生成测试场景，返回 {\"scenarios\": [...]}。每个接口必须覆盖 functional、boundary、"
            "exception、permission 四类；rule_indexes 指向 businessRules 的从零开始索引。\n"
            + _json_payload({"apiDefinitions": state["api_definitions"], "businessRules": state["business_rules"]}),
            ScenarioListOutput,
            lambda value: self._validate_scenarios(state, value),
        )
        updates = {"scenarios": [scenario.model_dump(mode="json") for scenario in output.scenarios]}
        await self._checkpoint("generate_test_scenarios", state, updates)
        return updates

    async def generate_structured_cases(self, state: TestGenerationState) -> dict[str, object]:
        """把场景转为请求模板和断言草稿；仍不发送任何测试请求。"""

        output = await self.llm.complete_structured(
            SYSTEM_PROMPT,
            "请基于已给出的场景生成结构化用例，返回 {\"cases\": [...]}。request_template 只允许 path、"
            "query、headers、body、auth 五个对象键，字段只能取 apiDefinitions 中对应 known_*_fields。"
            "scenario_index 和 rule_indexes 都是从零开始。\n"
            + _json_payload(
                {
                    "apiDefinitions": state["api_definitions"],
                    "businessRules": state["business_rules"],
                    "scenarios": state["scenarios"],
                }
            ),
            CaseListOutput,
            lambda value: self._validate_cases(state, value),
        )
        updates = {"generated_cases": [case.model_dump(mode="json") for case in output.cases]}
        await self._checkpoint("generate_structured_cases", state, updates)
        return updates

    async def validate_generated_cases(self, state: TestGenerationState) -> dict[str, object]:
        """再次确定性校验模型结果，确保绕过提示的字段或接口不会进入持久层。"""

        cases = [StructuredCaseDraft.model_validate(case) for case in state["generated_cases"]]
        self._validate_cases(state, CaseListOutput(cases=cases))
        updates = {"validation_errors": []}
        await self._checkpoint("validate_generated_cases", state, updates)
        return updates

    async def persist_drafts(self, state: TestGenerationState) -> dict[str, object]:
        """先写规则再写用例；所有用例固定为 draft，随后进入审核中断点。"""

        scope = {"project_id": UUID(state["project_id"]), "source_scan_id": UUID(state["source_scan_id"])}
        rules = [BusinessRuleDraft.model_validate(rule) for rule in state["business_rules"]]
        saved_rules = await self.tools.save_analysis_drafts(SaveAnalysisDraftInput(**scope, drafts=rules))
        cases = [StructuredCaseDraft.model_validate(case) for case in state["generated_cases"]]
        saved_cases = await self.tools.save_case_drafts(
            SaveCaseDraftInput(
                **scope,
                agent_run_id=self.run.id,
                rule_ids=saved_rules.rule_ids,
                cases=cases,
            )
        )
        await self.tools.mark_drafts_pending_review(
            MarkDraftsPendingReviewInput(**scope, agent_run_id=self.run.id)
        )
        self.run.status = AgentRunStatus.PENDING_REVIEW
        updates = {
            "persisted_rule_ids": [str(value) for value in saved_rules.rule_ids],
            "persisted_case_ids": [str(value) for value in saved_cases.test_case_ids],
            "review_status": "pending_review",
        }
        await self._checkpoint("persist_drafts", state, updates)
        return updates

    async def human_review_interrupt(self, state: TestGenerationState) -> dict[str, object]:
        """LangGraph 在进入本节点前暂停；恢复只接受人工审核的 approved 或 disabled 决策。"""

        # 正常执行不会越过 compile 的 interrupt_before；保留节点使审核边界在图定义中可见且可审计。
        return {"review_status": state["review_status"]}

    async def _checkpoint(self, node_name: str, state: TestGenerationState, updates: dict[str, object]) -> None:
        """把当前节点的可恢复摘要写入数据库，并独立提交防止进程中断丢失进度。"""

        merged = dict(state) | updates
        await self.tools.write_checkpoint(self.run, node_name, _checkpoint_summary(merged))
        await self.tools.session.commit()

    @staticmethod
    def _validate_rules(state: TestGenerationState, output: RuleListOutput) -> None:
        api_ids = set(state["api_definition_ids"])
        valid_chunks = {
            str(chunk["id"])
            for context in state["retrieved_context"].values()
            for chunk in context.get("chunks", [])
            if isinstance(chunk, dict) and "id" in chunk
        }
        for rule in output.rules:
            if str(rule.api_definition_id) not in api_ids:
                raise ValueError("规则引用了未选择的接口")
            if rule.source_type == BusinessRuleSourceType.SOURCE_CONFIRMED:
                if any(str(reference.knowledge_chunk_id) not in valid_chunks for reference in rule.evidence):
                    raise ValueError("源码确认规则引用了检索结果之外的代码切块")

    @staticmethod
    def _validate_scenarios(state: TestGenerationState, output: ScenarioListOutput) -> None:
        api_ids = set(state["api_definition_ids"])
        rule_count = len(state["business_rules"])
        categories_by_api: dict[str, set[TestCaseCategory]] = {}
        for scenario in output.scenarios:
            if str(scenario.api_definition_id) not in api_ids:
                raise ValueError("场景引用了未选择的接口")
            if any(index < 0 or index >= rule_count for index in scenario.rule_indexes):
                raise ValueError("场景引用了不存在的业务规则")
            categories_by_api.setdefault(str(scenario.api_definition_id), set()).add(scenario.category)
        required = set(TestCaseCategory)
        if any(categories_by_api.get(api_id, set()) != required for api_id in api_ids):
            raise ValueError("每个接口必须覆盖四类测试场景")

    @staticmethod
    def _validate_cases(state: TestGenerationState, output: CaseListOutput) -> None:
        apis = {str(api["id"]): ToolApiDefinition.model_validate(api) for api in state["api_definitions"]}
        scenarios = [TestScenarioDraft.model_validate(scenario) for scenario in state["scenarios"]]
        rules = [BusinessRuleDraft.model_validate(rule) for rule in state["business_rules"]]
        for case in output.cases:
            api = apis.get(str(case.api_definition_id))
            if api is None:
                raise ValueError("用例引用了未选择的接口")
            if case.scenario_index >= len(scenarios):
                raise ValueError("用例引用了不存在的测试场景")
            scenario = scenarios[case.scenario_index]
            if scenario.api_definition_id != case.api_definition_id or scenario.category != case.category:
                raise ValueError("用例必须匹配所属接口和场景类别")
            if any(index < 0 or index >= len(rules) for index in case.rule_indexes):
                raise ValueError("用例引用了不存在的业务规则")
            if any(rules[index].source_type == BusinessRuleSourceType.INFERRED for index in case.rule_indexes):
                if not case.is_inferred:
                    raise ValueError("引用 AI 推断规则的用例必须标记为推断")
            TestGenerationGraph._validate_request_fields(case, api)

    @staticmethod
    def _validate_request_fields(case: StructuredCaseDraft, api: ToolApiDefinition) -> None:
        """仅允许已由 M2 扫描得到的参数与 DTO 字段进入 Agent 草稿。"""

        template = case.request_template
        invalid_sections = set(template) - {"path", "query", "headers", "body", "auth"}
        if invalid_sections:
            raise ValueError("请求模板包含不支持的区段")
        allowed_by_section = {
            "path": set(api.known_path_fields),
            "query": set(api.known_query_fields),
            "headers": set(api.known_header_fields),
            "body": set(api.known_body_fields),
        }
        for section, allowed_fields in allowed_by_section.items():
            values = template.get(section, {})
            if not isinstance(values, dict):
                raise ValueError("请求模板区段必须是对象")
            if not set(values).issubset(allowed_fields):
                raise ValueError("用例包含接口中不存在的请求字段")
        if "auth" in template and not isinstance(template["auth"], dict):
            raise ValueError("认证配置必须是对象")


def _checkpoint_summary(state: dict[str, object]) -> dict[str, object]:
    """裁剪检查点：保留生成成果与标识，移除可能较大的源码检索全文。"""

    return {
        "apiDefinitionIds": state.get("api_definition_ids", []),
        "businessRules": state.get("business_rules", []),
        "scenarios": state.get("scenarios", []),
        "generatedCases": state.get("generated_cases", []),
        "persistedRuleIds": state.get("persisted_rule_ids", []),
        "persistedCaseIds": state.get("persisted_case_ids", []),
        "validationErrors": state.get("validation_errors", []),
        "reviewStatus": state.get("review_status", "draft"),
    }


def _json_payload(value: dict[str, object]) -> str:
    """统一 JSON 序列化，确保 UUID 等 Pydantic 值可安全进入提示。"""

    return json.dumps(value, ensure_ascii=False, default=str)
