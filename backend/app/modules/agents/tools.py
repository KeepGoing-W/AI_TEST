"""Agent 唯一允许使用的项目数据读取与草稿写入入口。"""

from collections import defaultdict
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import AppError
from app.modules.agents.models import AgentCheckpoint, AgentRun
from app.modules.agents.repository import AgentRepository
from app.modules.agents.schemas import BusinessRuleDraft, StructuredCaseDraft
from app.modules.knowledge.hybrid_retrieval import retrieve_hybrid_context
from app.modules.knowledge.models import BusinessRule
from app.modules.projects.repository import ProjectRepository
from app.modules.source_scans.models import ApiDefinition, CodeSymbol, RelationType
from app.modules.source_scans.repository import SourceScanRepository
from app.modules.testcases.models import TestAssertion, TestCase, TestCaseStatus
from app.modules.users.models import UserRole


class ToolScopeInput(BaseModel):
    """每个 Tool 都必须携带的项目和扫描版本边界。"""

    project_id: UUID
    source_scan_id: UUID


class ReadApiDefinitionsInput(ToolScopeInput):
    """读取已选接口时使用的受限输入。"""

    api_definition_ids: list[UUID] = Field(min_length=1, max_length=20)


class ToolApiDefinition(BaseModel):
    """提供给 Graph 与模型的接口定义摘要。"""

    id: UUID
    method: str
    normalized_path: str
    request_definition: dict[str, object]
    response_definition: dict[str, object]
    security_definition: dict[str, object]
    controller_symbol_id: UUID | None
    method_symbol_id: UUID | None
    known_path_fields: list[str]
    known_query_fields: list[str]
    known_header_fields: list[str]
    known_body_fields: list[str]


class ReadApiDefinitionsOutput(BaseModel):
    """接口读取结果。"""

    api_definitions: list[ToolApiDefinition]


class ReadSymbolsInput(ToolScopeInput):
    """按受控符号标识读取符号与关系。"""

    symbol_ids: list[UUID] = Field(default_factory=list, max_length=100)


class ToolCodeSymbol(BaseModel):
    """不包含原始文件内容的代码符号摘要。"""

    id: UUID
    qualified_name: str
    symbol_type: str
    start_line: int
    end_line: int
    metadata: dict[str, object]


class ToolSymbolRelation(BaseModel):
    """符号间的受控有向关系。"""

    source_symbol_id: UUID
    target_symbol_id: UUID
    relation_type: str


class ReadSymbolsOutput(BaseModel):
    """符号与关联读取结果。"""

    symbols: list[ToolCodeSymbol]
    relations: list[ToolSymbolRelation]


class SearchContextInput(ReadApiDefinitionsInput):
    """混合检索限定在已选接口与扫描版本内。"""

    query: str | None = Field(default=None, max_length=500)
    max_results: int = Field(default=12, ge=1, le=20)


class SearchContextOutput(BaseModel):
    """按接口分组的检索上下文。"""

    contexts: dict[str, dict[str, object]]


class ReadConfirmedRulesInput(ToolScopeInput):
    """仅允许读取同扫描版本中的已确认规则。"""


class ToolBusinessRule(BaseModel):
    """已确认规则的最小展示字段。"""

    id: UUID
    content: str
    source_symbol_id: UUID | None
    evidence: dict[str, object]


class ReadConfirmedRulesOutput(BaseModel):
    """已确认规则读取结果。"""

    rules: list[ToolBusinessRule]


class SaveAnalysisDraftInput(ToolScopeInput):
    """保存已被 Pydantic 校验的规则草稿。"""

    drafts: list[BusinessRuleDraft] = Field(max_length=100)


class SaveAnalysisDraftOutput(BaseModel):
    """规则草稿落库后返回稳定标识。"""

    rule_ids: list[UUID]


class SaveCaseDraftInput(ToolScopeInput):
    """保存结构化用例草稿时使用的完整、已校验输入。"""

    agent_run_id: UUID
    rule_ids: list[UUID]
    cases: list[StructuredCaseDraft] = Field(max_length=100)


class SaveCaseDraftOutput(BaseModel):
    """用例草稿保存结果。"""

    test_case_ids: list[UUID]


class MarkDraftsPendingReviewInput(ToolScopeInput):
    """将同一运行新生成的草稿移入待审核状态。"""

    agent_run_id: UUID


class MarkDraftsPendingReviewOutput(BaseModel):
    """待审核状态迁移结果。"""

    count: int


class AgentTools:
    """以用户身份执行的受控 Tool 集合。

    Graph 不持有数据库模型，也不能读取磁盘、执行 Shell 或发起任意网络访问；所有平台数据
    都必须经过本类。每个公开方法首先重新校验用户的项目权限，因此即使未来 Graph 的调用入口
    增加，也不会因漏用 Router 依赖而越权。
    """

    def __init__(self, session: AsyncSession, user_id: UUID, user_role: UserRole) -> None:
        self.session = session
        self.user_id = user_id
        self.user_role = user_role

    async def read_api_definitions(self, payload: ReadApiDefinitionsInput) -> ReadApiDefinitionsOutput:
        """读取运行指定的接口及可生成字段白名单。"""

        await self._validate_scope(payload)
        repository = AgentRepository(self.session)
        definitions = await repository.get_api_definitions(
            payload.project_id, payload.source_scan_id, payload.api_definition_ids
        )
        if len(definitions) != len(set(payload.api_definition_ids)):
            raise AppError("API_DEFINITION_NOT_FOUND", "接口定义不存在或不属于当前扫描版本", 404)
        return ReadApiDefinitionsOutput(
            api_definitions=[await self._serialize_api_definition(definition) for definition in definitions]
        )

    async def read_symbols(self, payload: ReadSymbolsInput) -> ReadSymbolsOutput:
        """读取受限符号及从这些符号出发的关系。"""

        await self._validate_scope(payload)
        repository = AgentRepository(self.session)
        symbols = await repository.get_symbols(payload.source_scan_id, payload.symbol_ids)
        relations = await repository.list_symbol_relations(payload.source_scan_id, payload.symbol_ids)
        return ReadSymbolsOutput(
            symbols=[self._serialize_symbol(symbol) for symbol in symbols],
            relations=[
                ToolSymbolRelation(
                    source_symbol_id=relation.source_symbol_id,
                    target_symbol_id=relation.target_symbol_id,
                    relation_type=relation.relation_type.value,
                )
                for relation in relations
            ],
        )

    async def search_context(self, payload: SearchContextInput) -> SearchContextOutput:
        """对每个已选接口调用混合检索，结果不会脱离项目和扫描版本边界。"""

        await self._validate_scope(payload)
        contexts: dict[str, dict[str, object]] = {}
        for api_id in payload.api_definition_ids:
            result = await retrieve_hybrid_context(
                self.session,
                payload.project_id,
                payload.source_scan_id,
                api_id,
                payload.query,
                payload.max_results,
            )
            contexts[str(api_id)] = result.model_dump(mode="json")
        return SearchContextOutput(contexts=contexts)

    async def read_confirmed_rules(self, payload: ReadConfirmedRulesInput) -> ReadConfirmedRulesOutput:
        """读取同一扫描版本内已由源码确认的规则。"""

        await self._validate_scope(payload)
        rules = await AgentRepository(self.session).list_confirmed_rules(payload.project_id, payload.source_scan_id)
        return ReadConfirmedRulesOutput(
            rules=[
                ToolBusinessRule(
                    id=rule.id,
                    content=rule.content,
                    source_symbol_id=rule.source_symbol_id,
                    evidence=rule.evidence,
                )
                for rule in rules
            ]
        )

    async def save_analysis_drafts(self, payload: SaveAnalysisDraftInput) -> SaveAnalysisDraftOutput:
        """保存规则草稿，推断标记和来源证据不由调用方自行丢弃。"""

        await self._validate_scope(payload)
        records: list[BusinessRule] = []
        for draft in payload.drafts:
            source_symbol_id = next(
                (reference.source_symbol_id for reference in draft.evidence if reference.source_symbol_id is not None), None
            )
            # evidence 保留接口归属与全部来源，UI 可据此跳转到对应代码位置。
            evidence = {
                "apiDefinitionId": str(draft.api_definition_id),
                "confidence": draft.confidence,
                "references": [reference.model_dump(mode="json") for reference in draft.evidence],
            }
            records.append(
                BusinessRule(
                    project_id=payload.project_id,
                    source_scan_id=payload.source_scan_id,
                    source_symbol_id=source_symbol_id,
                    source_type=draft.source_type,
                    content=draft.content,
                    evidence=evidence,
                )
            )
        self.session.add_all(records)
        await self.session.flush()
        return SaveAnalysisDraftOutput(rule_ids=[record.id for record in records])

    async def save_case_drafts(self, payload: SaveCaseDraftInput) -> SaveCaseDraftOutput:
        """保存已校验的用例与断言，并固定为不可执行的草稿状态。"""

        await self._validate_scope(payload)
        if await AgentRepository(self.session).get_run(payload.project_id, payload.agent_run_id) is None:
            raise AppError("AGENT_RUN_NOT_FOUND", "Agent 运行不存在", 404)
        definitions = await AgentRepository(self.session).get_api_definitions(
            payload.project_id,
            payload.source_scan_id,
            [case.api_definition_id for case in payload.cases],
        )
        if len(definitions) != len({case.api_definition_id for case in payload.cases}):
            raise AppError("API_DEFINITION_NOT_FOUND", "用例引用了不存在的接口", 422)
        cases: list[TestCase] = []
        for draft in payload.cases:
            rule_ids = [payload.rule_ids[index] for index in draft.rule_indexes]
            case = TestCase(
                project_id=payload.project_id,
                source_scan_id=payload.source_scan_id,
                api_definition_id=draft.api_definition_id,
                agent_run_id=payload.agent_run_id,
                name=draft.name,
                description=draft.description,
                category=draft.category,
                priority=draft.priority,
                status=TestCaseStatus.DRAFT,
                preconditions=draft.preconditions,
                request_template=draft.request_template,
                source_rule_ids=[str(rule_id) for rule_id in rule_ids],
                source_symbol_ids=[str(symbol_id) for symbol_id in draft.source_symbol_ids],
                confidence=draft.confidence,
                is_inferred=draft.is_inferred,
            )
            cases.append(case)
        self.session.add_all(cases)
        # UUID 主键由 SQLAlchemy 在 flush 时生成；先 flush 后再创建断言，避免外键引用空值。
        await self.session.flush()
        assertions = []
        for case, draft in zip(cases, payload.cases, strict=True):
            for position, assertion in enumerate(draft.assertions, start=1):
                assertions.append(
                    TestAssertion(
                        test_case_id=case.id,
                        position=position,
                        assertion_type=assertion.assertion_type,
                        config=assertion.config,
                        description=assertion.description,
                    )
                )
        self.session.add_all(assertions)
        await self.session.flush()
        return SaveCaseDraftOutput(test_case_ids=[case.id for case in cases])

    async def mark_drafts_pending_review(
        self, payload: MarkDraftsPendingReviewInput
    ) -> MarkDraftsPendingReviewOutput:
        """将刚落库的草稿迁移为待审核；这一状态是执行器的硬性阻断前置条件。"""

        await self._validate_scope(payload)
        cases = await AgentRepository(self.session).list_test_cases(payload.project_id, payload.agent_run_id)
        for case in cases:
            if case.status == TestCaseStatus.DRAFT:
                case.status = TestCaseStatus.PENDING_REVIEW
        await self.session.flush()
        return MarkDraftsPendingReviewOutput(count=len(cases))

    async def write_checkpoint(self, run: AgentRun, node_name: str, state: dict[str, object]) -> None:
        """在每个节点完成后持久化可恢复的精简状态。"""

        checkpoints = await AgentRepository(self.session).list_checkpoints(run.id)
        # JSONB 只写入 Graph 的结构化中间产物，避免把提示词和源码全文重复持久化。
        checkpoint = AgentCheckpoint(
            agent_run_id=run.id,
            sequence=len(checkpoints) + 1,
            node_name=node_name,
            state=state,
        )
        self.session.add(checkpoint)
        run.current_node = node_name
        run.state_summary = state
        await self.session.flush()

    async def _validate_scope(self, payload: ToolScopeInput) -> None:
        """重复校验项目成员、扫描版本，防止 Tool 被单独调用时越权。"""

        project_repository = ProjectRepository(self.session)
        if await project_repository.get_by_id(payload.project_id) is None:
            raise AppError("PROJECT_NOT_FOUND", "项目不存在", 404)
        if self.user_role != UserRole.ADMIN and not await project_repository.has_member(payload.project_id, self.user_id):
            raise AppError("PROJECT_ACCESS_DENIED", "无权访问该项目", 403)
        if await SourceScanRepository(self.session).get_scan(payload.project_id, payload.source_scan_id) is None:
            raise AppError("SOURCE_SCAN_NOT_FOUND", "扫描任务不存在", 404)

    async def _serialize_api_definition(self, api: ApiDefinition) -> ToolApiDefinition:
        """从接口参数、DTO 关系提取 Agent 允许引用的请求字段。"""

        method_symbol_id = api.method_symbol_id
        parameter_groups = self._extract_parameter_groups(api.request_definition)
        body_fields = await self._get_body_fields(api.source_scan_id, method_symbol_id)
        return ToolApiDefinition(
            id=api.id,
            method=api.method,
            normalized_path=api.normalized_path,
            request_definition=api.request_definition,
            response_definition=api.response_definition,
            security_definition=api.security_definition,
            controller_symbol_id=api.controller_symbol_id,
            method_symbol_id=method_symbol_id,
            known_path_fields=sorted(parameter_groups["path"]),
            known_query_fields=sorted(parameter_groups["query"]),
            known_header_fields=sorted(parameter_groups["header"]),
            known_body_fields=sorted(body_fields),
        )

    @staticmethod
    def _extract_parameter_groups(request_definition: dict[str, object]) -> dict[str, set[str]]:
        """兼容源码与 OpenAPI 合并前后的参数结构，生成固定字段白名单。"""

        groups: dict[str, set[str]] = defaultdict(set)
        candidates: list[object] = [request_definition]
        source = request_definition.get("source")
        openapi = request_definition.get("openapi")
        if isinstance(source, dict):
            candidates.append(source)
        if isinstance(openapi, dict):
            candidates.append(openapi)
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            parameters = candidate.get("parameters")
            if not isinstance(parameters, list):
                continue
            for parameter in parameters:
                if not isinstance(parameter, dict):
                    continue
                source_type = parameter.get("source") or parameter.get("in")
                name = parameter.get("bindingName") or parameter.get("name")
                if isinstance(source_type, str) and isinstance(name, str) and source_type in {"path", "query", "header"}:
                    groups[source_type].add(name)
        return groups

    async def _get_body_fields(self, source_scan_id: UUID, method_symbol_id: UUID | None) -> set[str]:
        """根据 M2 已识别的 USES_DTO 关系限定 JSON 请求体字段。"""

        if method_symbol_id is None:
            return set()
        repository = AgentRepository(self.session)
        relations = await repository.list_symbol_relations(source_scan_id, [method_symbol_id])
        dto_ids = [
            relation.target_symbol_id
            for relation in relations
            if relation.relation_type == RelationType.USES_DTO
        ]
        dto_symbols = await repository.get_symbols(source_scan_id, dto_ids)
        dto_id_set = {symbol.id for symbol in dto_symbols}
        if not dto_id_set:
            return set()
        # 使用同一扫描版本和已识别 DTO 标识限定字段读取范围。
        values = await repository.list_child_symbols(source_scan_id, dto_id_set)
        return {symbol.name for symbol in values if symbol.symbol_type.value == "field"}

    @staticmethod
    def _serialize_symbol(symbol: CodeSymbol) -> ToolCodeSymbol:
        return ToolCodeSymbol(
            id=symbol.id,
            qualified_name=symbol.qualified_name,
            symbol_type=symbol.symbol_type.value,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            metadata=symbol.metadata_,
        )
