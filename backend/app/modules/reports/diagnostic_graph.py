"""失败诊断独立 LangGraph；只读执行快照与扫描符号，不参与断言。"""

from typing import Protocol, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from app.modules.executions.models import ExecutionStep
from app.modules.source_scans.models import ApiDefinition, CodeSymbol


class DiagnosticState(TypedDict):
    category: str
    evidence: dict[str, object]
    source_references: list[object]
    hypotheses: list[object]


class CompiledDiagnosticGraph(Protocol):
    async def ainvoke(self, input: DiagnosticState) -> DiagnosticState: ...


class FailureDiagnosticGraph:
    """通过固定节点把执行事实、源码引用和假设清晰分开。"""

    def __init__(self, step: ExecutionStep, api: ApiDefinition | None, symbols: list[CodeSymbol]) -> None:
        self.step = step
        self.api = api
        self.symbols = symbols

    def compile(self) -> CompiledDiagnosticGraph:
        graph = StateGraph(DiagnosticState)
        graph.add_node("classify_failure", self.classify_failure)
        graph.add_node("load_related_source", self.load_related_source)
        graph.add_node("generate_hypotheses", self.generate_hypotheses)
        graph.add_edge(START, "classify_failure")
        graph.add_edge("classify_failure", "load_related_source")
        graph.add_edge("load_related_source", "generate_hypotheses")
        graph.add_edge("generate_hypotheses", END)
        return cast(CompiledDiagnosticGraph, graph.compile())

    async def classify_failure(self, _: DiagnosticState) -> dict[str, object]:
        category = self.step.error_category.value if self.step.error_category is not None else "execution"
        return {
            "category": category,
            "evidence": {
                "stepStatus": self.step.status.value,
                "errorCode": self.step.error_code,
                "errorMessage": self.step.error_message,
                "requestSnapshot": self.step.request_snapshot,
                "responseSnapshot": self.step.response_snapshot,
                "extractedVariables": self.step.extracted_variables,
            },
        }

    async def load_related_source(self, _: DiagnosticState) -> dict[str, object]:
        references: list[object] = []
        if self.api is not None:
            references.append({"apiDefinitionId": str(self.api.id), "method": self.api.method, "path": self.api.normalized_path})
        for symbol in self.symbols:
            references.append({"symbolId": str(symbol.id), "qualifiedName": symbol.qualified_name, "startLine": symbol.start_line, "endLine": symbol.end_line})
        return {"source_references": references}

    async def generate_hypotheses(self, state: DiagnosticState) -> dict[str, object]:
        category = state["category"]
        messages = {
            "assertion": "响应已返回，但实际结果与已审核断言不一致；请先核对期望值、环境数据和接口业务分支。",
            "precondition": "下游请求缺少运行变量，通常由上游失败、提取规则未命中或步骤顺序导致。",
            "variable_extraction": "上游响应无法按配置提取唯一变量；请核对响应结构、响应头或文本捕获组。",
            "timeout": "请求超时；可能是测试环境不可用、接口耗时超限或依赖服务阻塞。",
            "connection": "无法建立连接；请核对测试环境地址、网络连通性和 Host 白名单。",
            "security": "请求被安全策略拒绝；请核对环境类型、写请求确认与目标 Host。",
        }
        summary = messages.get(category, "执行出现非预期错误；请结合错误码、请求响应快照和关联源码排查。")
        # 诊断是基于证据的低风险假设，明确标记而不改变确定性执行结论。
        return {"hypotheses": [{"summary": summary, "confidence": 0.5, "kind": "hypothesis"}]}
