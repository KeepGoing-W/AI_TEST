from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import AppError
from app.config import get_settings
from app.modules.knowledge.embedding import create_embedding_task
from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.source_scans.repository import SourceScanRepository


async def retry_embeddings(session: AsyncSession, project_id: UUID, source_scan_id: UUID, user_id: UUID) -> UUID:
    """仅对未超过重试上限的失败切块创建新的独立任务。"""

    if await SourceScanRepository(session).get_scan(project_id, source_scan_id) is None:
        raise AppError("SOURCE_SCAN_NOT_FOUND", "扫描任务不存在", 404)
    repository = KnowledgeRepository(session)
    if await repository.has_active_embedding_task(project_id, source_scan_id):
        raise AppError("EMBEDDING_TASK_ALREADY_RUNNING", "Embedding 任务正在执行", 409)
    if await repository.count_retryable_embedding_chunks(source_scan_id, get_settings().embedding_max_attempts) == 0:
        raise AppError("EMBEDDING_RETRY_EXHAUSTED", "没有可重试的 Embedding 切块", 409)
    task = await create_embedding_task(session, project_id, source_scan_id, user_id)
    await session.commit()
    return task.id
