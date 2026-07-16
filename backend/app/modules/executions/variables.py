"""变量替换和受控请求构造。"""

import re
from dataclasses import dataclass
from typing import TypeAlias
from urllib.parse import quote, urljoin, urlparse

from app.common.errors import AppError

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
_VARIABLE_PATTERN = re.compile(r"\{\{(env|secret|runtime)\.([A-Za-z_][A-Za-z0-9_]*)\}\}")
_PATH_PARAMETER_PATTERN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True)
class BuiltRequest:
    """已完成变量替换但尚未发送的请求。"""

    method: str
    url: str
    headers: dict[str, str]
    query: dict[str, str]
    json_body: JsonValue | None
    text_body: str | None


def resolve_template(value: JsonValue, namespaces: dict[str, dict[str, object]]) -> JsonValue:
    """递归替换变量；整个字符串是变量时保留原始类型。"""

    if isinstance(value, list):
        return [resolve_template(item, namespaces) for item in value]
    if isinstance(value, dict):
        return {key: resolve_template(item, namespaces) for key, item in value.items()}
    if not isinstance(value, str):
        return value
    full_match = _VARIABLE_PATTERN.fullmatch(value)
    if full_match is not None:
        # 单变量保留原类型，数值断言不会被意外转换为字符串。
        return _get_variable(full_match.group(1), full_match.group(2), namespaces)

    def replace(match: re.Match[str]) -> str:
        return str(_get_variable(match.group(1), match.group(2), namespaces))

    return _VARIABLE_PATTERN.sub(replace, value)


def find_runtime_variables(value: object) -> set[str]:
    """递归找出流程请求会消费的运行变量，供保存流程时校验生产顺序。"""

    if isinstance(value, dict):
        return set().union(*(find_runtime_variables(item) for item in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(find_runtime_variables(item) for item in value)) if value else set()
    if not isinstance(value, str):
        return set()
    return {match.group(2) for match in _VARIABLE_PATTERN.finditer(value) if match.group(1) == "runtime"}


def build_request(
    method: str,
    normalized_path: str,
    base_url: str,
    common_headers: dict[str, str],
    request_template: dict[str, object],
    namespaces: dict[str, dict[str, object]],
) -> BuiltRequest:
    """只接受已审核用例的固定区段，避免执行时引入任意请求配置。"""

    allowed_sections = {"path", "query", "headers", "body", "auth"}
    invalid_sections = set(request_template) - allowed_sections
    if invalid_sections:
        raise AppError("REQUEST_TEMPLATE_INVALID", "请求模板包含不支持的区段", 400)
    resolved = resolve_template(request_template, namespaces)
    if not isinstance(resolved, dict):
        raise AppError("REQUEST_TEMPLATE_INVALID", "请求模板必须是对象", 400)
    path_values = _as_string_mapping(resolved.get("path", {}), "path")
    query = _as_string_mapping(resolved.get("query", {}), "query")
    headers = {**common_headers, **_as_string_mapping(resolved.get("headers", {}), "headers")}
    path = _PATH_PARAMETER_PATTERN.sub(lambda match: _replace_path_parameter(match, path_values), normalized_path)
    if _PATH_PARAMETER_PATTERN.search(path) is not None:
        raise AppError("REQUEST_PATH_VARIABLE_MISSING", "路径变量缺失", 400)
    try:
        parsed_base = urlparse(base_url)
        base_hostname = parsed_base.hostname
        base_port = parsed_base.port
    except ValueError as exc:
        raise AppError("REQUEST_TARGET_INVALID", "请求目标无效", 400) from exc
    if (
        parsed_base.scheme not in {"http", "https"}
        or base_hostname is None
        or parsed_base.username is not None
        or parsed_base.password is not None
    ):
        raise AppError("REQUEST_TARGET_INVALID", "请求目标无效", 400)
    url = urljoin(_ensure_trailing_slash(base_url), path.lstrip("/"))
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise AppError("REQUEST_TARGET_INVALID", "请求目标无效", 400) from exc
    if (
        parsed.scheme != parsed_base.scheme
        or hostname != base_hostname
        or port != base_port
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise AppError("REQUEST_TARGET_INVALID", "请求目标无效", 400)
    _apply_auth(headers, query, resolved.get("auth"))
    body = resolved.get("body")
    if isinstance(body, str):
        return BuiltRequest(method=method, url=url, headers=headers, query=query, json_body=None, text_body=body)
    if body is not None and not isinstance(body, (dict, list, int, float, bool)):
        raise AppError("REQUEST_BODY_INVALID", "请求体类型不支持", 400)
    return BuiltRequest(method=method, url=url, headers=headers, query=query, json_body=body, text_body=None)


def _get_variable(namespace: str, key: str, namespaces: dict[str, dict[str, object]]) -> object:
    value = namespaces.get(namespace, {}).get(key)
    if value is None:
        raise AppError("EXECUTION_VARIABLE_MISSING", f"变量 {namespace}.{key} 未配置", 400)
    return value


def _as_string_mapping(value: object, section_name: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise AppError("REQUEST_TEMPLATE_INVALID", f"{section_name} 必须是对象", 400)
    if any(not isinstance(key, str) for key in value):
        raise AppError("REQUEST_TEMPLATE_INVALID", f"{section_name} 键必须是字符串", 400)
    return {key: str(item) for key, item in value.items()}


def _replace_path_parameter(match: re.Match[str], values: dict[str, str]) -> str:
    name = match.group(1)
    if name not in values:
        return match.group(0)
    return quote(values[name], safe="")


def _apply_auth(headers: dict[str, str], query: dict[str, str], value: object) -> None:
    if value is None:
        return
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        raise AppError("REQUEST_AUTH_INVALID", "认证配置无效", 400)
    auth_type = value["type"]
    if auth_type == "bearer" and isinstance(value.get("token"), str):
        headers["Authorization"] = f"Bearer {value['token']}"
        return
    if auth_type == "basic" and isinstance(value.get("username"), str) and isinstance(value.get("password"), str):
        import base64

        credentials = f"{value['username']}:{value['password']}".encode()
        headers["Authorization"] = f"Basic {base64.b64encode(credentials).decode()}"
        return
    if auth_type == "api_key" and isinstance(value.get("name"), str) and isinstance(value.get("value"), str):
        if value.get("in") == "query":
            query[value["name"]] = value["value"]
        else:
            headers[value["name"]] = value["value"]
        return
    raise AppError("REQUEST_AUTH_INVALID", "认证配置无效", 400)


def _ensure_trailing_slash(value: str) -> str:
    return value if value.endswith("/") else f"{value}/"
