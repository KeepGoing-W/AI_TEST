import hashlib
import re
from dataclasses import dataclass
from uuid import UUID

from app.modules.knowledge.models import KnowledgeChunk, KnowledgeChunkType
from app.modules.source_scans.models import CodeSymbol, SourceFile, SymbolType

SQL_ANNOTATION_PATTERN = re.compile(r"@(Select|Insert|Update|Delete)\s*\(", re.MULTILINE)


@dataclass(frozen=True)
class SourceChunk:
    """尚未持久化的语义源码切块。"""

    source_file_id: UUID
    code_symbol_id: UUID | None
    chunk_type: KnowledgeChunkType
    content: str
    start_line: int
    end_line: int
    metadata: dict[str, object]


def build_knowledge_chunks(
    project_id: UUID,
    source_scan_id: UUID,
    source_files: list[SourceFile],
    symbols: list[CodeSymbol],
) -> list[KnowledgeChunk]:
    """按类、方法、DTO、异常和 SQL 定义生成源码切块，绝不按固定字符数拆分。"""

    files_by_id = {source_file.id: source_file for source_file in source_files}
    chunks: list[SourceChunk] = []
    for symbol in symbols:
        source_file = files_by_id.get(symbol.source_file_id)
        if source_file is None:
            continue
        chunk_type = _symbol_chunk_type(symbol)
        if chunk_type is None:
            continue
        content = _line_range(source_file.content, symbol.start_line, symbol.end_line)
        if not content:
            continue
        chunks.append(
            SourceChunk(
                source_file_id=source_file.id,
                code_symbol_id=symbol.id,
                chunk_type=chunk_type,
                content=content,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                metadata={"qualifiedName": symbol.qualified_name, "symbolType": symbol.symbol_type.value},
            )
        )
    for source_file in source_files:
        chunks.extend(_sql_chunks(source_file))
    return [
        KnowledgeChunk(
            project_id=project_id,
            source_scan_id=source_scan_id,
            source_file_id=chunk.source_file_id,
            code_symbol_id=chunk.code_symbol_id,
            chunk_type=chunk.chunk_type,
            content=chunk.content,
            content_sha256=hashlib.sha256(chunk.content.encode("utf-8")).hexdigest(),
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            metadata_=chunk.metadata,
        )
        for chunk in chunks
    ]


def _symbol_chunk_type(symbol: CodeSymbol) -> KnowledgeChunkType | None:
    if symbol.symbol_type == SymbolType.METHOD:
        return KnowledgeChunkType.METHOD
    if symbol.symbol_type == SymbolType.DTO:
        return KnowledgeChunkType.DTO
    if symbol.symbol_type == SymbolType.EXCEPTION:
        return KnowledgeChunkType.EXCEPTION
    if symbol.symbol_type in {
        SymbolType.CLASS,
        SymbolType.INTERFACE,
        SymbolType.ENUM,
        SymbolType.REPOSITORY,
        SymbolType.MAPPER,
    }:
        return KnowledgeChunkType.CLASS
    return None


def _line_range(content: str, start_line: int, end_line: int) -> str:
    return "\n".join(content.splitlines()[start_line - 1 : end_line]).strip()


def _sql_chunks(source_file: SourceFile) -> list[SourceChunk]:
    chunks: list[SourceChunk] = []
    for match in SQL_ANNOTATION_PATTERN.finditer(source_file.content):
        end = _annotation_end(source_file.content, match.end() - 1)
        if end is None:
            continue
        content = source_file.content[match.start() : end].strip()
        if not content:
            continue
        start_line = source_file.content.count("\n", 0, match.start()) + 1
        end_line = source_file.content.count("\n", 0, end) + 1
        chunks.append(
            SourceChunk(
                source_file_id=source_file.id,
                code_symbol_id=None,
                chunk_type=KnowledgeChunkType.SQL,
                content=content,
                start_line=start_line,
                end_line=end_line,
                metadata={"annotation": match.group(1)},
            )
        )
    return chunks


def _annotation_end(content: str, opening_parenthesis: int) -> int | None:
    depth = 0
    in_string = False
    escaped = False
    for index in range(opening_parenthesis, len(content)):
        character = content[index]
        if in_string:
            if character == '"' and not escaped:
                in_string = False
            escaped = character == "\\" and not escaped
            continue
        if character == '"':
            in_string = True
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    return None
