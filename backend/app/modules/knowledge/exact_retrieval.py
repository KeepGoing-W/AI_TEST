from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.modules.knowledge.models import KnowledgeChunk
from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.knowledge.search import KeywordSearchHit, search_with_ripgrep
from app.modules.projects.models import SourceArtifact
from app.modules.projects.repository import ProjectRepository
from app.modules.source_scans.models import ApiDefinition, CodeSymbol, SymbolRelation
from app.modules.source_scans.repository import SourceScanRepository

# 两跳足以覆盖 Controller -> Service -> DTO/异常，避免关系图过大导致无关代码进入上下文。
MAX_RELATION_DEPTH = 2


@dataclass(frozen=True)
class ExactRetrievalResult:
    """接口精确定位与关系扩展结果。"""

    api_definition: ApiDefinition
    symbols: list[CodeSymbol]
    chunks: list[KnowledgeChunk]
    keyword_hits: list[KeywordSearchHit]


async def retrieve_exact_context(
    session: AsyncSession,
    project_id: UUID,
    source_scan_id: UUID,
    api_definition_id: UUID,
) -> ExactRetrievalResult | None:
    """先精确定位 Controller，再沿受限关系扩展 DTO、Service 和异常符号。"""

    # 接口定义中的 controller_symbol_id 和 method_symbol_id 是精确检索的起点。
    source_repository = SourceScanRepository(session)
    api_definition = await source_repository.get_api_definition(project_id, source_scan_id, api_definition_id)
    if api_definition is None:
        return None
    knowledge_repository = KnowledgeRepository(session)
    symbols = await knowledge_repository.list_symbols(source_scan_id)
    symbols_by_id = {symbol.id: symbol for symbol in symbols}
    # 先扩展结构化关系，再补充关键词命中；向量召回在混合检索阶段执行。
    selected_ids = _expand_symbol_ids(
        {value for value in [api_definition.controller_symbol_id, api_definition.method_symbol_id] if value is not None},
        symbols,
        await knowledge_repository.list_relations(source_scan_id),
    )
    selected_symbols = [symbol for symbol in symbols if symbol.id in selected_ids]
    chunks = await knowledge_repository.list_chunks_by_symbol_ids(source_scan_id, selected_ids)
    artifact = await _scan_artifact(session, project_id, source_scan_id)
    keyword_hits: list[KeywordSearchHit] = []
    # ripgrep 只接收扫描出的符号名，不接受客户端传入的任意命令或路径。
    for symbol_id in [api_definition.method_symbol_id, api_definition.controller_symbol_id]:
        symbol = symbols_by_id.get(symbol_id) if symbol_id is not None else None
        if symbol is not None:
            keyword_hits.extend(search_with_ripgrep(artifact, symbol.name, get_settings()))
    return ExactRetrievalResult(
        api_definition=api_definition,
        symbols=selected_symbols,
        chunks=chunks,
        keyword_hits=_deduplicate_keyword_hits(keyword_hits),
    )


def _expand_symbol_ids(seed_ids: set[UUID], symbols: list[CodeSymbol], relations: list[SymbolRelation]) -> set[UUID]:
    selected_ids = set(seed_ids)
    parent_by_id = {symbol.id: symbol.parent_symbol_id for symbol in symbols}
    # 方法符号本身不包含 Controller 类时，先补上其父符号以保留路由上下文。
    for symbol_id in tuple(seed_ids):
        parent_id = parent_by_id.get(symbol_id)
        if parent_id is not None:
            selected_ids.add(parent_id)
    frontier = set(selected_ids)
    for _ in range(MAX_RELATION_DEPTH):
        next_frontier: set[UUID] = set()
        for relation in relations:
            # 调用/引用关系按双向查看，既能从 Controller 找 Service，也能从 DTO 回溯使用点。
            if relation.source_symbol_id in frontier and relation.target_symbol_id not in selected_ids:
                next_frontier.add(relation.target_symbol_id)
            if relation.target_symbol_id in frontier and relation.source_symbol_id not in selected_ids:
                next_frontier.add(relation.source_symbol_id)
        if not next_frontier:
            break
        selected_ids.update(next_frontier)
        frontier = next_frontier
    return selected_ids


async def _scan_artifact(
    session: AsyncSession, project_id: UUID, source_scan_id: UUID
) -> SourceArtifact | None:
    scan = await SourceScanRepository(session).get_scan(project_id, source_scan_id)
    if scan is None or scan.source_artifact_id is None:
        return None
    return await ProjectRepository(session).get_source_artifact_by_id(scan.source_artifact_id)


def _deduplicate_keyword_hits(hits: list[KeywordSearchHit]) -> list[KeywordSearchHit]:
    unique_hits: dict[tuple[str, int], KeywordSearchHit] = {}
    for hit in hits:
        # 同一行可能同时命中 Controller 和方法名，只保留一条补充证据。
        unique_hits.setdefault((hit.relative_path, hit.line_number), hit)
    return list(unique_hits.values())
