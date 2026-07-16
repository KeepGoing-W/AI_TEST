import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from app.common.network import NetworkTargetError, approve_http_target, validate_stable_dns
from app.config import Settings
from app.modules.projects.models import OpenApiSourceType

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


class OpenApiParseError(Exception):
    """表示可安全反馈的 OpenAPI 读取或解析失败。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class OpenApiOperation:
    """规范化后的 OpenAPI 操作定义。"""

    method: str
    normalized_path: str
    operation_id: str | None
    request_definition: dict[str, object]
    response_definition: dict[str, object]
    security_definition: dict[str, object]
    openapi_definition: dict[str, object]


async def load_openapi_operations(
    source_type: OpenApiSourceType | None, location: str | None, settings: Settings
) -> list[OpenApiOperation]:
    """从已登记 URL 或受控文件读取并解析 OpenAPI 文档。"""

    if source_type is None or location is None:
        return []
    if source_type == OpenApiSourceType.URL:
        content = await _read_url(location, settings)
    elif source_type == OpenApiSourceType.FILE:
        content = await asyncio.to_thread(_read_file, location, settings)
    else:
        raise OpenApiParseError("OPENAPI_SOURCE_INVALID", "OpenAPI 来源无效")
    return _parse_document(content)


async def _read_url(location: str, settings: Settings) -> bytes:
    try:
        allowlist = [item for item in settings.openapi_host_allowlist.split(",") if item.strip()]
        target = await approve_http_target(location, allowlist)
        await validate_stable_dns(target)
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=settings.default_request_timeout_seconds,
        ) as client:
            async with client.stream("GET", location) as response:
                response.raise_for_status()
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > settings.max_openapi_document_bytes:
                        raise OpenApiParseError("OPENAPI_DOCUMENT_TOO_LARGE", "OpenAPI 文档超过大小限制")
                    chunks.append(chunk)
    except (httpx.HTTPError, NetworkTargetError) as exc:
        raise OpenApiParseError("OPENAPI_URL_UNAVAILABLE", "OpenAPI 地址不可访问") from exc
    return b"".join(chunks)


def _read_file(location: str, settings: Settings) -> bytes:
    try:
        path = Path(location).resolve(strict=True)
    except OSError as exc:
        raise OpenApiParseError("OPENAPI_FILE_NOT_FOUND", "OpenAPI 文件不可访问") from exc
    root = (settings.source_upload_root.resolve() / "openapi").resolve()
    if not path.is_file() or not path.is_relative_to(root):
        raise OpenApiParseError("OPENAPI_FILE_NOT_ALLOWED", "OpenAPI 文件不在允许范围内")
    if path.stat().st_size > settings.max_openapi_document_bytes:
        raise OpenApiParseError("OPENAPI_DOCUMENT_TOO_LARGE", "OpenAPI 文档超过大小限制")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise OpenApiParseError("OPENAPI_FILE_NOT_FOUND", "OpenAPI 文件不可访问") from exc


def _parse_document(content: bytes) -> list[OpenApiOperation]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        try:
            parsed = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            raise OpenApiParseError("OPENAPI_DOCUMENT_INVALID", "OpenAPI 文档格式无效") from exc
    if not isinstance(parsed, dict) or not str(parsed.get("openapi", "")).startswith(("3.0", "3.1")):
        raise OpenApiParseError("OPENAPI_VERSION_UNSUPPORTED", "仅支持 OpenAPI 3.0 和 3.1")
    parsed = json.loads(json.dumps(parsed, default=str))
    paths = parsed.get("paths")
    if not isinstance(paths, dict):
        raise OpenApiParseError("OPENAPI_DOCUMENT_INVALID", "OpenAPI 文档缺少 paths")
    operations: list[OpenApiOperation] = []
    for path, path_item in paths.items():
        if not isinstance(path, str) or not isinstance(path_item, dict):
            continue
        common_parameters = _as_list(path_item.get("parameters"))
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            parameters = common_parameters + _as_list(operation.get("parameters"))
            request_definition = {"parameters": parameters, "requestBody": operation.get("requestBody") or {}}
            operations.append(
                OpenApiOperation(
                    method=method.upper(),
                    normalized_path=_normalize_path(path),
                    operation_id=_as_string(operation.get("operationId")),
                    request_definition=request_definition,
                    response_definition={"responses": operation.get("responses") or {}},
                    security_definition={"security": operation.get("security", parsed.get("security", []))},
                    openapi_definition={"path": path, "operation": operation},
                )
            )
    return operations


def _normalize_path(path: str) -> str:
    segments = [segment for segment in path.split("/") if segment]
    return "/" + "/".join(segments) if segments else "/"


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _as_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def compare_request_definitions(
    source_definition: dict[str, object], openapi_definition: dict[str, object]
) -> list[dict[str, object]]:
    """比较同一路由的请求定义，并保留可展示的差异。"""

    source_parameters = source_definition.get("parameters")
    openapi_parameters = openapi_definition.get("parameters")
    source_bindings = {
        (str(parameter.get("source")), str(parameter.get("bindingName") or parameter.get("name")))
        for parameter in source_parameters
        if isinstance(parameter, dict)
    } if isinstance(source_parameters, list) else set()
    openapi_bindings = {
        (str(parameter.get("in")), str(parameter.get("name")))
        for parameter in openapi_parameters
        if isinstance(parameter, dict)
    } if isinstance(openapi_parameters, list) else set()
    conflicts: list[dict[str, object]] = []
    if source_bindings and openapi_bindings and source_bindings != openapi_bindings:
        conflicts.append(
            {
                "field": "parameters",
                "source": sorted(source_bindings),
                "openapi": sorted(openapi_bindings),
            }
        )
    source_has_body = any(binding[0] == "body" for binding in source_bindings)
    openapi_has_body = bool(openapi_definition.get("requestBody"))
    if source_has_body != openapi_has_body:
        conflicts.append(
            {"field": "requestBody", "source": source_has_body, "openapi": openapi_has_body}
        )
    return conflicts
