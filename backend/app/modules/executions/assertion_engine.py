"""不依赖 LLM 的确定性断言引擎。"""

import json
import re
from dataclasses import dataclass

from app.common.errors import AppError

_JSON_PATH_TOKEN = re.compile(r"(?:\.([A-Za-z_][A-Za-z0-9_-]*))|(?:\[(\d+|\*)\])|(?:\[['\"]([^'\"]+)['\"]\])")
# 兼容 M4 已生成的旧断言名称，避免历史草稿无法执行。
_ALIASES = {"status_code": "status_code_equals", "business_code": "business_code_equals", "text_contains": "body_contains"}


@dataclass(frozen=True)
class AssertionEvaluation:
    assertion_type: str
    path: str | None
    expected: object | None
    actual: object | None
    passed: bool
    message: str


def evaluate_assertion(
    assertion_type: str,
    config: dict[str, object],
    status_code: int,
    body_text: str,
    body_json: object | None,
    duration_ms: int,
) -> AssertionEvaluation:
    """按照配置直接计算 Pass/Fail，AI 结果不参与最终判断。"""

    normalized_type = _ALIASES.get(assertion_type, assertion_type)
    if normalized_type == "status_code_equals":
        return _equals(normalized_type, None, config.get("expected"), status_code, "状态码")
    if normalized_type == "business_code_equals":
        path = _config_path(config, "$.code")
        return _equals(normalized_type, path, config.get("expected"), _json_path_values(body_json, path), "业务码")
    if normalized_type == "json_path_equals":
        path = _config_path(config)
        return _equals(normalized_type, path, config.get("expected"), _json_path_values(body_json, path), "JSONPath")
    if normalized_type in {"json_path_exists", "json_path_not_exists"}:
        path = _config_path(config)
        values = _json_path_values(body_json, path)
        exists = bool(values)
        passed = exists if normalized_type == "json_path_exists" else not exists
        return AssertionEvaluation(normalized_type, path, exists, exists, passed, "JSONPath 存在性符合预期" if passed else "JSONPath 存在性不符合预期")
    if normalized_type == "json_path_type":
        path = _config_path(config)
        values = _json_path_values(body_json, path)
        expected = config.get("expected")
        actual = _json_type(values[0]) if len(values) == 1 else None
        passed = isinstance(expected, str) and len(values) == 1 and actual == expected
        return AssertionEvaluation(normalized_type, path, expected, actual, passed, "JSON 类型符合预期" if passed else "JSON 类型不符合预期")
    if normalized_type in {"body_contains", "body_not_contains"}:
        expected = config.get("expected")
        if not isinstance(expected, str):
            raise AppError("ASSERTION_CONFIG_INVALID", "文本断言缺少 expected 字符串", 400)
        contained = expected in body_text
        passed = contained if normalized_type == "body_contains" else not contained
        return AssertionEvaluation(normalized_type, None, expected, contained, passed, "响应文本符合预期" if passed else "响应文本不符合预期")
    if normalized_type == "number_range":
        path = _config_path(config)
        values = _json_path_values(body_json, path)
        actual = values[0] if len(values) == 1 else None
        minimum, maximum = config.get("min"), config.get("max")
        passed = isinstance(actual, (int, float)) and not isinstance(actual, bool)
        passed = passed and (minimum is None or isinstance(minimum, (int, float)) and actual >= minimum)
        passed = passed and (maximum is None or isinstance(maximum, (int, float)) and actual <= maximum)
        return AssertionEvaluation(normalized_type, path, {"min": minimum, "max": maximum}, actual, passed, "数值范围符合预期" if passed else "数值范围不符合预期")
    if normalized_type == "response_time_less_than":
        expected = config.get("expected")
        passed = isinstance(expected, int) and expected >= 0 and duration_ms < expected
        return AssertionEvaluation(normalized_type, None, expected, duration_ms, passed, "响应耗时符合预期" if passed else "响应耗时超出限制")
    raise AppError("ASSERTION_TYPE_UNSUPPORTED", "断言类型不支持", 400)


def parse_response_json(body_text: str) -> object | None:
    try:
        return json.loads(body_text)
    except json.JSONDecodeError:
        return None


def _equals(assertion_type: str, path: str | None, expected: object | None, actual: object, label: str) -> AssertionEvaluation:
    resolved_actual = actual[0] if isinstance(actual, list) and len(actual) == 1 else actual
    passed = resolved_actual == expected
    return AssertionEvaluation(assertion_type, path, expected, resolved_actual, passed, f"{label}符合预期" if passed else f"{label}不符合预期")


def _config_path(config: dict[str, object], default: str | None = None) -> str:
    value = config.get("path", default)
    if not isinstance(value, str):
        raise AppError("ASSERTION_CONFIG_INVALID", "JSONPath 断言缺少 path", 400)
    return value


def _json_path_values(value: object | None, path: str) -> list[object]:
    if value is None or not path.startswith("$"):
        return []
    current = [value]
    offset = 1
    while offset < len(path):
        # 只支持安全的字段、下标和通配符，不执行 JSONPath 过滤表达式。
        match = _JSON_PATH_TOKEN.match(path, offset)
        if match is None:
            raise AppError("ASSERTION_JSON_PATH_INVALID", "JSONPath 格式不支持", 400)
        key = match.group(1) or match.group(3)
        index = match.group(2)
        next_values: list[object] = []
        for item in current:
            if key is not None and isinstance(item, dict) and key in item:
                next_values.append(item[key])
            elif index == "*" and isinstance(item, list):
                next_values.extend(item)
            elif index is not None and index != "*" and isinstance(item, list) and int(index) < len(item):
                next_values.append(item[int(index)])
        current = next_values
        offset = match.end()
    return current


def extract_json_path_values(value: object | None, path: str) -> list[object]:
    """复用与断言一致的受限 JSONPath 语法，不允许流程配置执行过滤表达式。"""

    return _json_path_values(value, path)


def _json_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    return "object"
