from collections import defaultdict
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import AppError
from app.config import get_settings
from app.modules.knowledge.embedding import EmbeddingError, get_default_embedding_provider
from app.modules.knowledge.exact_retrieval import ExactRetrievalResult, retrieve_exact_context
from app.modules.knowledge.models import KnowledgeChunk
from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.knowledge.schemas import (
    KeywordSearchHitResponse,
    KnowledgeContextChunkResponse,
    KnowledgeContextResponse,
)
from app.modules.source_scans.models import CodeSymbol, SourceFile
from app.modules.source_scans.repository import SourceScanRepository


async def retrieve_hybrid_context(
    session: AsyncSession,
    project_id: UUID,
    source_scan_id: UUID,
    api_definition_id: UUID,
    query: str | None,
    max_results: int | None,
) -> KnowledgeContextResponse:
    """合并精确和语义结果，按引用重排并在返回前裁剪上下文预算。"""

    exact = await retrieve_exact_context(session, project_id, source_scan_id, api_definition_id)
    if exact is None:
        raise AppError("API_DEFINITION_NOT_FOUND", "接口定义不存在", 404)
    scan = await SourceScanRepository(session).get_scan(project_id, source_scan_id)
    if scan is None:
        raise AppError("SOURCE_SCAN_NOT_FOUND", "扫描任务不存在", 404)
    settings = get_settings()
    limit = min(max_results or settings.knowledge_context_max_results, settings.knowledge_context_max_results)
    sources_by_chunk_id: dict[UUID, set[str]] = defaultdict(set)
    scores_by_chunk_id: dict[UUID, float] = {}
    chunks_by_id: dict[UUID, KnowledgeChunk] = {}
    _add_exact_chunks(exact, chunks_by_id, scores_by_chunk_id, sources_by_chunk_id)
    embedding_available = await _add_vector_chunks(
        session,
        source_scan_id,
        _embedding_query(exact, query),
        chunks_by_id,
        scores_by_chunk_id,
        sources_by_chunk_id,
    )
    source_files = {value.id: value for value in await KnowledgeRepository(session).list_source_files(source_scan_id)}
    symbols = {value.id: value for value in await KnowledgeRepository(session).list_symbols(source_scan_id)}
    ranked_chunks = sorted(
        chunks_by_id.values(),
        key=lambda chunk: (-scores_by_chunk_id[chunk.id], chunk.start_line, str(chunk.id)),
    )
    response_chunks = _apply_context_budget(
        ranked_chunks,
        source_files,
        symbols,
        scores_by_chunk_id,
        sources_by_chunk_id,
        scan.scan_version,
        limit,
        settings.knowledge_context_max_characters,
    )
    return KnowledgeContextResponse(
        api_definition_id=api_definition_id,
        scan_version=scan.scan_version,
        chunks=response_chunks,
        keyword_hits=[
            KeywordSearchHitResponse(
                source_file_path=hit.relative_path,
                line_number=hit.line_number,
                line_content=hit.line_content,
                scan_version=scan.scan_version,
            )
            for hit in exact.keyword_hits
        ],
        embedding_available=embedding_available,
    )


def _add_exact_chunks(
    exact: ExactRetrievalResult,
    chunks_by_id: dict[UUID, KnowledgeChunk],
    scores_by_chunk_id: dict[UUID, float],
    sources_by_chunk_id: dict[UUID, set[str]],
) -> None:
    controller_id = exact.api_definition.controller_symbol_id
    method_id = exact.api_definition.method_symbol_id
    for chunk in exact.chunks:
        chunks_by_id[chunk.id] = chunk
        sources_by_chunk_id[chunk.id].add("exact")
        if chunk.code_symbol_id == method_id:
            scores_by_chunk_id[chunk.id] = 1.0
        elif chunk.code_symbol_id == controller_id:
            scores_by_chunk_id[chunk.id] = 0.95
        else:
            scores_by_chunk_id[chunk.id] = 0.85


async def _add_vector_chunks(
    session: AsyncSession,
    source_scan_id: UUID,
    query: str,
    chunks_by_id: dict[UUID, KnowledgeChunk],
    scores_by_chunk_id: dict[UUID, float],
    sources_by_chunk_id: dict[UUID, set[str]],
) -> bool:
    provider = await get_default_embedding_provider(session)
    if provider is None:
        return False
    try:
        embedding = (await provider.embed([query]))[0]
    except (EmbeddingError, IndexError):
        return False
    candidates = await KnowledgeRepository(session).search_by_embedding(
        source_scan_id,
        embedding,
        get_settings().knowledge_vector_candidate_count,
    )
    for chunk, distance in candidates:
        chunks_by_id[chunk.id] = chunk
        sources_by_chunk_id[chunk.id].add("vector")
        scores_by_chunk_id[chunk.id] = max(scores_by_chunk_id.get(chunk.id, 0.0), max(0.0, 1.0 - distance) * 0.8)
    return True


def _embedding_query(exact: ExactRetrievalResult, query: str | None) -> str:
    parts = [exact.api_definition.method, exact.api_definition.normalized_path]
    if query is not None and query.strip():
        parts.append(query.strip())
    return " ".join(parts)


def _apply_context_budget(
    chunks: list[KnowledgeChunk],
    source_files: dict[UUID, SourceFile],
    symbols: dict[UUID, CodeSymbol],
    scores_by_chunk_id: dict[UUID, float],
    sources_by_chunk_id: dict[UUID, set[str]],
    scan_version: int,
    limit: int,
    character_budget: int,
) -> list[KnowledgeContextChunkResponse]:
    remaining = character_budget
    values: list[KnowledgeContextChunkResponse] = []
    for chunk in chunks:
        if len(values) >= limit or remaining <= 0:
            break
        content = chunk.content
        original_characters = len(content)
        truncated = original_characters > remaining
        content = content[:remaining] if truncated else content
        if not content:
            break
        source_file = source_files.get(chunk.source_file_id)
        symbol = symbols.get(chunk.code_symbol_id) if chunk.code_symbol_id is not None else None
        values.append(
            KnowledgeContextChunkResponse(
                id=chunk.id,
                chunk_type=chunk.chunk_type.value,
                source_file_path=source_file.relative_path if source_file is not None else "",
                code_symbol=symbol.qualified_name if symbol is not None else None,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                content=content,
                original_characters=original_characters,
                truncated=truncated,
                score=round(scores_by_chunk_id[chunk.id], 4),
                retrieval_sources=sorted(sources_by_chunk_id[chunk.id]),
                scan_version=scan_version,
            )
        )
        remaining -= len(content)
    return values
