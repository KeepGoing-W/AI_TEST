"""执行证据的脱敏与 cURL 生成。"""

import json
import re
import shlex
from urllib.parse import urlencode

from app.modules.executions.variables import BuiltRequest

_SENSITIVE_KEYWORDS = ("authorization", "token", "cookie", "password", "secret", "api-key", "apikey")
_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(?i)((?:authorization|token|cookie|password|secret|api[_-]?key)\s*[:=]\s*[\"']?)[^\s\",'&}]+"
)


def redact_value(value: object, key: str | None = None) -> object:
    """按字段名递归脱敏，不让密钥进入执行记录和前端。"""

    if key is not None and _is_sensitive_key(key):
        return "***"
    if isinstance(value, dict):
        return {str(item_key): redact_value(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {key: "***" if _is_sensitive_key(key) else value for key, value in headers.items()}


def redact_text(value: str) -> str:
    """处理无法解析为 JSON 的文本响应或文本请求体。"""

    return _SENSITIVE_TEXT_PATTERN.sub(r"\1***", value)


def build_redacted_curl(request: BuiltRequest) -> str:
    """基于脱敏快照生成可复制 cURL。"""

    redacted_query = {key: "***" if _is_sensitive_key(key) else value for key, value in request.query.items()}
    target_url = request.url if not redacted_query else f"{request.url}?{urlencode(redacted_query)}"
    parts = ["curl", "-X", request.method, shlex.quote(target_url)]
    for key, value in redact_headers(request.headers).items():
        parts.extend(["-H", shlex.quote(f"{key}: {value}")])
    if request.text_body is not None:
        parts.extend(["--data-raw", shlex.quote(redact_text(request.text_body))])
    elif request.json_body is not None:
        parts.extend(["--data-raw", shlex.quote(json.dumps(redact_value(request.json_body), ensure_ascii=False))])
    return " ".join(parts)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("_", "-")
    return any(keyword in normalized for keyword in _SENSITIVE_KEYWORDS)
