from uuid import UUID

from pydantic import BaseModel


class KnowledgeContextChunkResponse(BaseModel):
    """混合检索返回的源码上下文。"""

    id: UUID
    chunk_type: str
    source_file_path: str
    code_symbol: str | None
    start_line: int
    end_line: int
    content: str
    original_characters: int
    truncated: bool
    score: float
    retrieval_sources: list[str]
    scan_version: int


class KeywordSearchHitResponse(BaseModel):
    """关键词搜索补充命中。"""

    source_file_path: str
    line_number: int
    line_content: str
    scan_version: int


class KnowledgeContextResponse(BaseModel):
    """单接口的受限混合检索结果。"""

    api_definition_id: UUID
    scan_version: int
    chunks: list[KnowledgeContextChunkResponse]
    keyword_hits: list[KeywordSearchHitResponse]
    embedding_available: bool


class EmbeddingRetryResponse(BaseModel):
    """Embedding 重试任务响应。"""

    task_id: UUID
    source_scan_id: UUID

