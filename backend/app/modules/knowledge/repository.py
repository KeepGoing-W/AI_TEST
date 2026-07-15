from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.knowledge.models import EmbeddingStatus, KnowledgeChunk
from app.modules.source_scans.models import BackgroundTask, CodeSymbol, SourceFile, SymbolRelation, TaskStatus, TaskType


class KnowledgeRepository:
    """知识库数据访问。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add_chunks(self, chunks: list[KnowledgeChunk]) -> None:
        self.session.add_all(chunks)

    async def list_source_files(self, source_scan_id: UUID) -> list[SourceFile]:
        values = await self.session.scalars(select(SourceFile).where(SourceFile.source_scan_id == source_scan_id))
        return list(values)

    async def list_symbols(self, source_scan_id: UUID) -> list[CodeSymbol]:
        values = await self.session.scalars(select(CodeSymbol).where(CodeSymbol.source_scan_id == source_scan_id))
        return list(values)

    async def claim_embedding_chunks(
        self, source_scan_id: UUID, batch_size: int, max_attempts: int
    ) -> list[KnowledgeChunk]:
        statement = (
            select(KnowledgeChunk)
            .where(
                KnowledgeChunk.source_scan_id == source_scan_id,
                KnowledgeChunk.embedding_status.in_([EmbeddingStatus.PENDING, EmbeddingStatus.FAILED]),
                KnowledgeChunk.embedding_attempts < max_attempts,
            )
            .order_by(KnowledgeChunk.created_at)
            .with_for_update(skip_locked=True)
            .limit(batch_size)
        )
        values = list(await self.session.scalars(statement))
        for value in values:
            value.embedding_status = EmbeddingStatus.PROCESSING
            value.embedding_attempts += 1
            value.embedding_error = None
        return values

    async def count_retryable_embedding_chunks(self, source_scan_id: UUID, max_attempts: int) -> int:
        statement = select(KnowledgeChunk).where(
            KnowledgeChunk.source_scan_id == source_scan_id,
            KnowledgeChunk.embedding_status.in_([EmbeddingStatus.PENDING, EmbeddingStatus.FAILED]),
            KnowledgeChunk.embedding_attempts < max_attempts,
        )
        return len(list(await self.session.scalars(statement)))

    async def list_relations(self, source_scan_id: UUID) -> list[SymbolRelation]:
        values = await self.session.scalars(
            select(SymbolRelation).where(SymbolRelation.source_scan_id == source_scan_id)
        )
        return list(values)

    async def list_chunks_by_symbol_ids(self, source_scan_id: UUID, symbol_ids: set[UUID]) -> list[KnowledgeChunk]:
        if not symbol_ids:
            return []
        values = await self.session.scalars(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.source_scan_id == source_scan_id, KnowledgeChunk.code_symbol_id.in_(symbol_ids))
            .order_by(KnowledgeChunk.chunk_type, KnowledgeChunk.start_line)
        )
        return list(values)

    async def search_by_embedding(
        self, source_scan_id: UUID, embedding: list[float], limit: int
    ) -> list[tuple[KnowledgeChunk, float]]:
        distance = KnowledgeChunk.embedding.cosine_distance(embedding).label("distance")
        statement = (
            select(KnowledgeChunk, distance)
            .where(
                KnowledgeChunk.source_scan_id == source_scan_id,
                KnowledgeChunk.embedding_status == EmbeddingStatus.SUCCEEDED,
            )
            .order_by(distance)
            .limit(limit)
        )
        return [(chunk, float(value)) for chunk, value in (await self.session.execute(statement)).all()]

    async def has_active_embedding_task(self, project_id: UUID, source_scan_id: UUID) -> bool:
        statement = select(func.count()).select_from(BackgroundTask).where(
            BackgroundTask.project_id == project_id,
            BackgroundTask.task_type == TaskType.KNOWLEDGE_EMBEDDING,
            BackgroundTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
            BackgroundTask.payload["sourceScanId"].astext == str(source_scan_id),
        )
        return (await self.session.scalar(statement) or 0) > 0
