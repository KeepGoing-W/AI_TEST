"""流程响应变量提取；只支持固定来源，绝不执行表达式或脚本。"""

import re

from app.common.errors import AppError
from app.modules.executions.assertion_engine import extract_json_path_values
from app.modules.test_suites.models import VariableExtractionSource


def extract_runtime_value(source: VariableExtractionSource, expression: str | None, body_json: object | None, body_text: str, headers: dict[str, str], status_code: int) -> object:
    """从单个响应位置提取一个值；多值或空值均是流程前置条件失败。"""

    if source == VariableExtractionSource.STATUS_CODE:
        return status_code
    if source == VariableExtractionSource.JSON_PATH:
        return _single_value(extract_json_path_values(body_json, _required_expression(expression)))
    if source == VariableExtractionSource.RESPONSE_HEADER:
        expected = _required_expression(expression).lower()
        value = next((value for key, value in headers.items() if key.lower() == expected), None)
        if value is None:
            raise AppError("VARIABLE_EXTRACTION_FAILED", "响应头中未找到配置的变量", 409)
        return value
    if source == VariableExtractionSource.TEXT:
        # 文本提取只允许有限长度的单捕获组正则，防止把响应当作可执行规则或无限制处理。
        pattern = _required_expression(expression)
        if len(pattern) > 512 or len(body_text) > 1_048_576:
            raise AppError("VARIABLE_EXTRACTION_FAILED", "文本提取范围超出限制", 409)
        try:
            match = re.search(pattern, body_text)
        except re.error as exc:
            raise AppError("VARIABLE_EXTRACTION_FAILED", "文本提取表达式无效", 409) from exc
        if match is None or len(match.groups()) != 1 or match.group(1) == "":
            raise AppError("VARIABLE_EXTRACTION_FAILED", "文本提取必须匹配唯一的非空捕获组", 409)
        return match.group(1)
    raise AppError("VARIABLE_EXTRACTION_FAILED", "变量提取方式不支持", 409)


def _required_expression(value: str | None) -> str:
    if value is None or not value:
        raise AppError("VARIABLE_EXTRACTION_FAILED", "变量提取规则缺少 expression", 409)
    return value


def _single_value(values: list[object]) -> object:
    if len(values) != 1 or values[0] is None:
        raise AppError("VARIABLE_EXTRACTION_FAILED", "变量提取结果必须唯一且非空", 409)
    return values[0]
