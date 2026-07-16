from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

import httpx
from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.modules.knowledge.models import EmbeddingStatus, KnowledgeChunk
from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.llm_configs.models import LlmConfig
from app.modules.source_scans.models import BackgroundTask, TaskStatus, TaskType


class EmbeddingError(Exception):
    """Embedding 调用或返回结果不可用。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class EmbeddingProvider(Protocol):
    """Embedding Provider 的受控抽象。"""

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """为一批文本生成同维度向量。"""


class EmbeddingData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int = Field(ge=0)
    embedding: list[float]


class EmbeddingResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: list[EmbeddingData]


class OpenAiCompatibleEmbeddingProvider:
    """使用已配置 OpenAI 兼容 Provider 的 embeddings 接口。"""

    def __init__(self, config: LlmConfig) -> None:
        self.config = config

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            # 密钥只在调用 Provider 前短暂解密，不写入任务结果或异常信息。
            api_key = Fernet(get_settings().encryption_key.get_secret_value()).decrypt(
                self.config.encrypted_api_key.encode()
            ).decode()
        except (InvalidToken, TypeError, ValueError) as exc:
            raise EmbeddingError("EMBEDDING_CONFIG_INVALID", "Embedding 配置不可用") from exc
        try:
            async with httpx.AsyncClient(timeout=get_settings().embedding_timeout_seconds) as client:
                response = await client.post(
                    f"{self.config.base_url.rstrip('/')}/embeddings",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": get_settings().embedding_model or self.config.model,
                        "input": list(texts),
                    },
                )
                response.raise_for_status()
                # 先用 Pydantic 约束第三方响应结构，避免异常数据写入 pgvector。
                payload = EmbeddingResponse.model_validate(response.json())
        except (httpx.HTTPError, ValidationError) as exc:
            raise EmbeddingError("EMBEDDING_PROVIDER_FAILED", "Embedding Provider 调用失败") from exc
        # API 返回顺序不作为契约，必须依据 index 恢复与输入 texts 一一对应的顺序。
        ordered = sorted(payload.data, key=lambda item: item.index)
        if len(ordered) != len(texts) or [item.index for item in ordered] != list(range(len(texts))):
            raise EmbeddingError("EMBEDDING_RESPONSE_INVALID", "Embedding Provider 返回数量或顺序无效")
        dimensions = get_settings().embedding_dimensions
        if any(len(item.embedding) != dimensions for item in ordered):
            raise EmbeddingError("EMBEDDING_DIMENSION_MISMATCH", "Embedding 向量维度不匹配")
        return [item.embedding for item in ordered]


async def create_embedding_task(
    session: AsyncSession, project_id: UUID, source_scan_id: UUID, requested_by: UUID | None
) -> BackgroundTask:
    """为扫描版本创建独立的 Embedding 批处理任务。"""

    task = BackgroundTask(
        project_id=project_id,
        task_type=TaskType.KNOWLEDGE_EMBEDDING,
        payload={"sourceScanId": str(source_scan_id)},
        requested_by=requested_by,
    )
    session.add(task)
    return task


async def get_default_embedding_provider(session: AsyncSession) -> EmbeddingProvider | None:
    """返回默认启用的 Embedding Provider，不暴露其密钥。"""

    # 当前复用默认且启用的 LLM 配置，仅在配置存在时才尝试语义召回。
    config = await session.scalar(
        select(LlmConfig).where(LlmConfig.is_default.is_(True), LlmConfig.enabled.is_(True))
    )
    return OpenAiCompatibleEmbeddingProvider(config) if config is not None else None


async def process_embedding_task(session: AsyncSession, task: BackgroundTask) -> None:
    """处理一批切块；单批失败只影响该批切块，后续重试有次数上限。"""

    source_scan_id = _source_scan_id(task)
    settings = get_settings()
    async with session.begin():
        task.status = TaskStatus.RUNNING
        task.result = {"phase": "embedding", "processed": 0}
    processed = 0
    # 每次锁定一个批次后立即提交“处理中”状态，避免多个 Worker 重复生成同一切块。
    while True:
        async with session.begin():
            chunks = await KnowledgeRepository(session).claim_embedding_chunks(
                source_scan_id,
                settings.embedding_batch_size,
                settings.embedding_max_attempts,
            )
        if not chunks:
            async with session.begin():
                task.status = TaskStatus.SUCCEEDED
                task.result = {"phase": "completed", "processed": processed}
                task.completed_at = func.now()
            return
        async with session.begin():
            config = await session.scalar(
                select(LlmConfig).where(LlmConfig.is_default.is_(True), LlmConfig.enabled.is_(True))
            )
        if config is None:
            await _mark_embedding_failed(
                session,
                task,
                chunks,
                "EMBEDDING_CONFIG_NOT_FOUND",
                "未配置启用的默认 Embedding Provider",
            )
            return
        try:
            # 网络调用放在数据库事务之外，避免长时间占用行锁。
            vectors = await OpenAiCompatibleEmbeddingProvider(config).embed([chunk.content for chunk in chunks])
        except EmbeddingError as exc:
            await _mark_embedding_failed(session, task, chunks, exc.code, exc.message)
            return
        async with session.begin():
            # 只有整批向量均返回有效结果时才把切块标记为成功。
            for chunk, vector in zip(chunks, vectors, strict=True):
                chunk.embedding = vector
                chunk.embedding_status = EmbeddingStatus.SUCCEEDED
                chunk.embedding_error = None
            processed += len(chunks)
            task.result = {"phase": "embedding", "processed": processed}


async def _mark_embedding_failed(
    session: AsyncSession,
    task: BackgroundTask,
    chunks: list[KnowledgeChunk],
    error_code: str,
    error_message: str,
) -> None:
    async with session.begin():
        # 保留失败状态与错误码，由新的任务在尝试次数未耗尽时重新领取。
        for chunk in chunks:
            chunk.embedding_status = EmbeddingStatus.FAILED
            chunk.embedding_error = error_code
        task.status = TaskStatus.FAILED
        task.error_code = error_code
        task.error_message = error_message
        task.result = {"phase": "failed", "processed": 0}
        task.completed_at = func.now()


def _source_scan_id(task: BackgroundTask) -> UUID:
    value = task.payload.get("sourceScanId")
    if not isinstance(value, str):
        raise EmbeddingError("EMBEDDING_TASK_INVALID", "Embedding 任务缺少扫描版本")
    try:
        return UUID(value)
    except ValueError as exc:
        raise EmbeddingError("EMBEDDING_TASK_INVALID", "Embedding 任务扫描版本无效") from exc
