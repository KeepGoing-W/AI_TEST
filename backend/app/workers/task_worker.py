import asyncio
import logging
from uuid import UUID

from sqlalchemy import func

from app.config import get_settings
from app.database import async_session_factory
from app.modules.knowledge.chunker import build_knowledge_chunks
from app.modules.knowledge.embedding import create_embedding_task, process_embedding_task
from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.executions.service import process_execution_task
from app.modules.projects.repository import ProjectRepository
from app.modules.source_scans.java_parser import JavaParseError, parse_java_sources
from app.modules.source_scans.models import (
    ApiDefinition,
    CodeSymbol,
    RelationType,
    SourceFile,
    SymbolRelation,
    SymbolType,
    TaskStatus,
    TaskType,
)
from app.modules.source_scans.reader import SourceReadError, discover_java_files
from app.modules.source_scans.openapi_parser import (
    OpenApiParseError,
    compare_request_definitions,
    load_openapi_operations,
)
from app.modules.source_scans.repository import SourceScanRepository
from app.modules.source_scans.service import mark_scan_failed, mark_scan_running, mark_scan_succeeded

logger = logging.getLogger(__name__)


class TaskWorker:
    """从 PostgreSQL 领取并执行单进程后台任务。"""

    def __init__(self, poll_interval_seconds: float = 1.0) -> None:
        self.poll_interval_seconds = poll_interval_seconds
        self._stopped = asyncio.Event()

    async def run(self) -> None:
        while not self._stopped.is_set():
            processed = await self.process_next()
            if not processed:
                try:
                    await asyncio.wait_for(self._stopped.wait(), timeout=self.poll_interval_seconds)
                except TimeoutError:
                    pass

    def stop(self) -> None:
        self._stopped.set()

    async def process_next(self) -> bool:
        async with async_session_factory() as session:
            async with session.begin():
                task = await SourceScanRepository(session).claim_next_task()
                if task is None:
                    return False
                if task.task_type in {TaskType.KNOWLEDGE_EMBEDDING, TaskType.EXECUTION}:
                    task.started_at = func.now()
                else:
                    scan = await SourceScanRepository(session).get_scan_by_task_id(task.id)
                    if scan is None:
                        return True
                    await mark_scan_running(session, task, scan)
                    task.started_at = func.now()
                    scan.started_at = func.now()

            try:
                if task.task_type == TaskType.EXECUTION:
                    await process_execution_task(session, task)
                    return True
                if task.task_type == TaskType.KNOWLEDGE_EMBEDDING:
                    await process_embedding_task(session, task)
                    return True
                if task.task_type != TaskType.SOURCE_SCAN:
                    raise ValueError("UNSUPPORTED_TASK_TYPE")
                async with session.begin():
                    scan = await SourceScanRepository(session).get_scan_by_task_id(task.id)
                    if scan is None or scan.source_artifact_id is None:
                        raise SourceReadError("SOURCE_ARTIFACT_NOT_FOUND", "扫描来源不存在")
                    artifact = await ProjectRepository(session).get_source_artifact_by_id(scan.source_artifact_id)
                    if artifact is None:
                        raise SourceReadError("SOURCE_ARTIFACT_NOT_FOUND", "扫描来源不存在")
                    project = await ProjectRepository(session).get_by_id(scan.project_id)
                    if project is None:
                        raise SourceReadError("PROJECT_NOT_FOUND", "项目不存在")
                    openapi_source_type = project.openapi_source_type
                    openapi_location = project.openapi_location
                discovery = await asyncio.to_thread(discover_java_files, artifact, get_settings())
                async with session.begin():
                    scan = await SourceScanRepository(session).get_scan_by_task_id(task.id)
                    if scan is None:
                        return True
                    source_files = [
                        SourceFile(
                            source_scan_id=scan.id,
                            relative_path=file.relative_path,
                            content=file.content,
                            content_sha256=file.content_sha256,
                            size_bytes=file.size_bytes,
                        )
                        for file in discovery.files
                    ]
                    SourceScanRepository(session).add_source_files(source_files)
                    await session.flush()
                    source_file_inputs = [(source_file.id, source_file.content) for source_file in source_files]
                parse_result = await asyncio.to_thread(parse_java_sources, source_file_inputs)
                openapi_operations = await load_openapi_operations(
                    openapi_source_type,
                    openapi_location,
                    get_settings(),
                )
                async with session.begin():
                    scan = await SourceScanRepository(session).get_scan_by_task_id(task.id)
                    if scan is None:
                        return True
                    repository = SourceScanRepository(session)
                    code_symbols = [
                        CodeSymbol(
                            source_scan_id=scan.id,
                            source_file_id=symbol.source_file_id,
                            symbol_type=symbol.symbol_type,
                            name=symbol.name,
                            qualified_name=symbol.qualified_name,
                            signature=symbol.signature,
                            start_line=symbol.start_line,
                            end_line=symbol.end_line,
                            annotations=symbol.annotations,
                            metadata_=symbol.metadata,
                        )
                        for symbol in parse_result.code_symbols
                    ]
                    repository.add_code_symbols(code_symbols)
                    await session.flush()
                    symbols_by_qualified_name = {symbol.qualified_name: symbol for symbol in code_symbols}
                    for parsed_symbol, code_symbol in zip(parse_result.code_symbols, code_symbols, strict=True):
                        if parsed_symbol.parent_qualified_name is not None:
                            parent = symbols_by_qualified_name.get(parsed_symbol.parent_qualified_name)
                            if parent is not None:
                                code_symbol.parent_symbol_id = parent.id
                    symbols_by_name: dict[str, list[CodeSymbol]] = {}
                    for code_symbol in code_symbols:
                        if code_symbol.symbol_type in {SymbolType.FIELD, SymbolType.METHOD}:
                            continue
                        symbols_by_name.setdefault(code_symbol.name, []).append(code_symbol)
                    symbol_relations = []
                    relation_keys: set[tuple[UUID, UUID, RelationType]] = set()
                    for relation in parse_result.symbol_relations:
                        source_symbol = symbols_by_qualified_name.get(relation.source_qualified_name)
                        target_candidates = symbols_by_name.get(relation.target_name, [])
                        if source_symbol is None or len(target_candidates) != 1:
                            continue
                        target_symbol = target_candidates[0]
                        if (
                            relation.relation_type == RelationType.USES_DTO
                            and target_symbol.symbol_type != SymbolType.DTO
                        ):
                            continue
                        if (
                            relation.relation_type == RelationType.THROWS
                            and target_symbol.symbol_type != SymbolType.EXCEPTION
                        ):
                            continue
                        relation_key = (source_symbol.id, target_symbol.id, relation.relation_type)
                        if source_symbol.id == target_symbol.id or relation_key in relation_keys:
                            continue
                        relation_keys.add(relation_key)
                        symbol_relations.append(
                            SymbolRelation(
                                source_scan_id=scan.id,
                                source_symbol_id=source_symbol.id,
                                target_symbol_id=target_symbol.id,
                                relation_type=relation.relation_type,
                                metadata_=relation.metadata,
                            )
                        )
                    repository.add_symbol_relations(symbol_relations)
                    api_definitions = []
                    seen_routes: set[tuple[str, str]] = set()
                    for definition in parse_result.api_definitions:
                        route_key = (definition.method, definition.normalized_path)
                        if route_key in seen_routes:
                            continue
                        seen_routes.add(route_key)
                        api_definitions.append(
                            ApiDefinition(
                                project_id=scan.project_id,
                                source_scan_id=scan.id,
                                method=definition.method,
                                normalized_path=definition.normalized_path,
                                controller_symbol_id=symbols_by_qualified_name[
                                    definition.controller_qualified_name
                                ].id,
                                method_symbol_id=symbols_by_qualified_name[definition.method_qualified_name].id,
                                request_definition=definition.request_definition,
                                source_definition=definition.source_definition,
                            )
                        )
                    api_by_route = {
                        (definition.method, definition.normalized_path): definition for definition in api_definitions
                    }
                    for operation in openapi_operations:
                        source_api = api_by_route.get((operation.method, operation.normalized_path))
                        if source_api is None:
                            source_api = ApiDefinition(
                                project_id=scan.project_id,
                                source_scan_id=scan.id,
                                method=operation.method,
                                normalized_path=operation.normalized_path,
                            )
                            api_definitions.append(source_api)
                            api_by_route[(operation.method, operation.normalized_path)] = source_api
                        source_request = source_api.request_definition
                        conflicts = compare_request_definitions(source_request, operation.request_definition)
                        source_api.operation_id = operation.operation_id
                        source_api.request_definition = {
                            "source": source_request,
                            "openapi": operation.request_definition,
                        }
                        source_api.response_definition = operation.response_definition
                        source_api.security_definition = operation.security_definition
                        source_api.openapi_definition = operation.openapi_definition
                        source_api.conflicts = conflicts
                        source_api.is_conflicted = bool(conflicts)
                    repository.add_api_definitions(api_definitions)
                    knowledge_repository = KnowledgeRepository(session)
                    knowledge_chunks = build_knowledge_chunks(
                        scan.project_id,
                        scan.id,
                        source_files,
                        code_symbols,
                    )
                    knowledge_repository.add_chunks(knowledge_chunks)
                    await session.flush()
                    await create_embedding_task(session, scan.project_id, scan.id, scan.created_by)
                    summary = discovery.summary() | {
                        "apiDefinitions": len(api_definitions),
                        "openapiDefinitions": len(openapi_operations),
                        "codeSymbols": len(code_symbols),
                        "symbolRelations": len(symbol_relations),
                        "knowledgeChunks": len(knowledge_chunks),
                    }
                    await mark_scan_succeeded(session, task, scan, summary)
                    task.completed_at = func.now()
                    scan.completed_at = func.now()
            except SourceReadError as exc:
                logger.warning("源码扫描失败，task_id=%s，error_code=%s", task.id, exc.code)
                async with session.begin():
                    scan = await SourceScanRepository(session).get_scan_by_task_id(task.id)
                    if scan is not None:
                        await mark_scan_failed(session, task, scan, exc.code, exc.message)
                        task.completed_at = func.now()
                        scan.completed_at = func.now()
            except JavaParseError as exc:
                logger.warning("Java 源码解析失败，task_id=%s，error_code=%s", task.id, exc.code)
                async with session.begin():
                    scan = await SourceScanRepository(session).get_scan_by_task_id(task.id)
                    if scan is not None:
                        await mark_scan_failed(session, task, scan, exc.code, exc.message)
                        task.completed_at = func.now()
                        scan.completed_at = func.now()
            except OpenApiParseError as exc:
                logger.warning("OpenAPI 解析失败，task_id=%s，error_code=%s", task.id, exc.code)
                async with session.begin():
                    scan = await SourceScanRepository(session).get_scan_by_task_id(task.id)
                    if scan is not None:
                        await mark_scan_failed(session, task, scan, exc.code, exc.message)
                        task.completed_at = func.now()
                        scan.completed_at = func.now()
            except Exception:
                logger.exception("后台任务执行失败，task_id=%s", task.id)
                async with session.begin():
                    if task.task_type == TaskType.KNOWLEDGE_EMBEDDING:
                        task.status = TaskStatus.FAILED
                        task.error_code = "KNOWLEDGE_EMBEDDING_TASK_FAILED"
                        task.error_message = "知识向量任务执行失败"
                        task.completed_at = func.now()
                        return True
                    scan = await SourceScanRepository(session).get_scan_by_task_id(task.id)
                    if scan is not None:
                        await mark_scan_failed(session, task, scan, "SOURCE_SCAN_TASK_FAILED", "源码扫描任务执行失败")
                        task.completed_at = func.now()
                        scan.completed_at = func.now()
            return True
