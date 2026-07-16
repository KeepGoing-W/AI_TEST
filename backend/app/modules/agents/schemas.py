from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.agents.models import AgentErrorCategory, AgentRunStatus
from app.modules.knowledge.models import BusinessRuleSourceType
from app.modules.testcases.models import TestCaseCategory, TestCaseStatus

PROMPT_VERSION = "m4-testcase-generation-v1"


class SourceReference(BaseModel):
    """规则或场景可回溯到的源码切块与符号定位。"""

    source_symbol_id: UUID | None = None
    knowledge_chunk_id: UUID | None = None
    source_file_path: str = Field(min_length=1, max_length=2048)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_line_range(self) -> "SourceReference":
        if self.end_line < self.start_line:
            raise ValueError("来源结束行不能小于开始行")
        return self


class BusinessRuleDraft(BaseModel):
    """模型输出的业务规则；推断与源码事实必须明确分开。"""

    api_definition_id: UUID
    content: str = Field(min_length=1, max_length=2000)
    source_type: BusinessRuleSourceType
    confidence: float = Field(ge=0, le=1)
    evidence: list[SourceReference] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_evidence(self) -> "BusinessRuleDraft":
        if self.source_type == BusinessRuleSourceType.SOURCE_CONFIRMED and not self.evidence:
            raise ValueError("源码确认的规则必须至少包含一个来源")
        if self.source_type == BusinessRuleSourceType.INFERRED and self.confidence > 0.6:
            raise ValueError("AI 推断规则的置信度不能高于 0.6")
        return self


class TestScenarioDraft(BaseModel):
    """测试场景仅描述测试意图，尚未构造成可执行请求。"""

    api_definition_id: UUID
    category: TestCaseCategory
    name: str = Field(min_length=1, max_length=256)
    description: str = Field(min_length=1, max_length=2000)
    rule_indexes: list[int] = Field(min_length=1, max_length=20)
    source_symbol_ids: list[UUID] = Field(default_factory=list, max_length=50)
    confidence: float = Field(ge=0, le=1)


class AssertionDraft(BaseModel):
    """由 Agent 提议、后续由 M5 确定性解释器执行的断言定义。"""

    assertion_type: Literal[
        "status_code_equals", "business_code_equals", "json_path_equals", "json_path_exists", "json_path_not_exists",
        "json_path_type", "body_contains", "body_not_contains", "number_range", "response_time_less_than",
        "status_code", "business_code", "text_contains",
    ]
    config: dict[str, object] = Field(default_factory=dict)
    description: str = Field(default="", max_length=1000)


class StructuredCaseDraft(BaseModel):
    """通过 Pydantic 校验后的结构化用例草稿。"""

    api_definition_id: UUID
    scenario_index: int = Field(ge=0)
    name: str = Field(min_length=1, max_length=256)
    description: str = Field(min_length=1, max_length=2000)
    category: TestCaseCategory
    priority: Literal["P0", "P1", "P2", "P3"] = "P1"
    preconditions: list[str] = Field(default_factory=list, max_length=20)
    # 请求模板只保存结构；M5 才会将它构造成实际 HTTP 请求。
    request_template: dict[str, object] = Field(default_factory=dict)
    assertions: list[AssertionDraft] = Field(min_length=1, max_length=20)
    rule_indexes: list[int] = Field(min_length=1, max_length=20)
    source_symbol_ids: list[UUID] = Field(default_factory=list, max_length=50)
    confidence: float = Field(ge=0, le=1)
    is_inferred: bool = False


class TestcaseGenerationRequest(BaseModel):
    """启动单扫描版本 Agent 分析与用例生成的请求。"""

    source_scan_id: UUID
    api_definition_ids: list[UUID] = Field(min_length=1, max_length=20)
    llm_config_id: UUID | None = None


class AgentRunResponse(BaseModel):
    """Agent 运行详情响应，不携带模型原始响应或源码全文。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    source_scan_id: UUID
    api_definition_ids: list[UUID]
    status: AgentRunStatus
    current_node: str
    prompt_version: str
    model_snapshot: dict[str, object]
    state_summary: dict[str, object]
    error_category: AgentErrorCategory | None
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AgentRunProgressEvent(BaseModel):
    """前端节点轨道使用的最小 SSE 状态载荷。"""

    run_id: UUID
    status: AgentRunStatus
    current_node: str
    error_code: str | None


class ReviewRequest(BaseModel):
    """人工审核将同一 Agent 运行下的所有草稿统一置为目标状态。"""

    status: Literal["approved", "disabled"]


class TestAssertionResponse(BaseModel):
    """用例详情中的断言响应。"""

    id: UUID
    position: int
    assertion_type: str
    config: dict[str, object]
    description: str


class TestCaseResponse(BaseModel):
    """前端编辑、审核和展示使用的用例响应。"""

    id: UUID
    project_id: UUID
    source_scan_id: UUID
    api_definition_id: UUID
    api_method: str
    api_path: str
    agent_run_id: UUID | None
    name: str
    description: str
    category: TestCaseCategory
    priority: str
    status: TestCaseStatus
    preconditions: list[str]
    request_template: dict[str, object]
    source_rule_ids: list[UUID]
    source_symbol_ids: list[UUID]
    confidence: float
    is_inferred: bool
    assertions: list[TestAssertionResponse]
    created_at: datetime
    updated_at: datetime


class TestCaseUpdateRequest(BaseModel):
    """人工审核前允许编辑的用例字段，避免意外改写溯源字段。"""

    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    priority: Literal["P0", "P1", "P2", "P3"] | None = None
    preconditions: list[str] | None = Field(default=None, max_length=20)
    request_template: dict[str, object] | None = None
    assertions: list[AssertionDraft] | None = Field(default=None, min_length=1, max_length=20)
