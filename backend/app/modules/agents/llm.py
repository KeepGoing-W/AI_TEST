"""OpenAI 兼容 LLM 的最小受控调用封装。"""

import json
from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

import httpx
from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import AppError
from app.config import get_settings
from app.modules.llm_configs.models import LlmConfig

OutputModel = TypeVar("OutputModel", bound=BaseModel)


class AgentLlmError(Exception):
    """LLM 调用或结构化输出失败，保留有限且脱敏的诊断摘要。"""

    def __init__(self, code: str, message: str, raw_preview: str = "") -> None:
        self.code = code
        self.message = message
        self.raw_preview = raw_preview
        super().__init__(message)


async def resolve_llm_config(session: AsyncSession, config_id: UUID | None) -> LlmConfig:
    """读取用户指定配置或启用的默认配置，绝不向调用方返回密钥。"""

    if config_id is not None:
        config = await session.get(LlmConfig, config_id)
    else:
        config = await session.scalar(
            select(LlmConfig).where(LlmConfig.enabled.is_(True), LlmConfig.is_default.is_(True))
        )
    if config is None or not config.enabled:
        raise AppError("LLM_CONFIG_NOT_FOUND", "未找到启用的 LLM 配置", 409)
    return config


def model_snapshot(config: LlmConfig) -> dict[str, object]:
    """生成可审计但不含 API Key 的模型参数快照。"""

    return {
        "provider": config.provider,
        "baseUrl": config.base_url,
        "model": config.model,
        "temperature": config.temperature,
        "maxOutputTokens": config.max_output_tokens,
        "contextWindow": config.context_window,
    }


class AgentLlmClient:
    """仅允许固定 OpenAI 兼容路径和 JSON 输出的 Agent 模型客户端。"""

    def __init__(self, config: LlmConfig) -> None:
        self.config = config

    async def complete_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        output_model: type[OutputModel],
        validate: Callable[[OutputModel], None] | None = None,
    ) -> OutputModel:
        """请求模型并校验结构化结果；格式或业务结构不合格时最多修复一次。"""

        raw_output = await self._request(system_prompt, user_prompt)
        try:
            return self._validate(raw_output, output_model, validate)
        except AgentLlmError as first_error:
            # 修复提示仅包含失败原因和模型的 JSON，不重新附带源码上下文，防止无谓扩大暴露面。
            repair_prompt = (
                "上一次输出不符合 JSON 结构或平台约束。请只返回修正后的 JSON，不要解释。\n"
                f"校验错误：{first_error.message}\n原始输出：{raw_output}"
            )
            repaired_output = await self._request(system_prompt, repair_prompt)
            try:
                return self._validate(repaired_output, output_model, validate)
            except AgentLlmError as second_error:
                raise AgentLlmError(
                    "AGENT_OUTPUT_INVALID",
                    "模型输出两次均未通过结构化校验",
                    _redact_preview(repaired_output),
                ) from second_error

    async def _request(self, system_prompt: str, user_prompt: str) -> str:
        """调用固定的 chat/completions 路径，并将网络、鉴权和协议错误归为模型错误。"""

        try:
            api_key = Fernet(get_settings().encryption_key.get_secret_value()).decrypt(
                self.config.encrypted_api_key.encode()
            ).decode()
        except (InvalidToken, ValueError, TypeError) as exc:
            raise AgentLlmError("LLM_CREDENTIAL_INVALID", "LLM 密钥无法解密") from exc
        payload = {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_output_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=get_settings().agent_llm_timeout_seconds) as client:
                response = await client.post(
                    f"{self.config.base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("模型未返回文本内容")
            return content
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AgentLlmError("LLM_REQUEST_FAILED", "模型调用失败") from exc

    @staticmethod
    def _validate(
        raw_output: str, output_model: type[OutputModel], validate: Callable[[OutputModel], None] | None
    ) -> OutputModel:
        try:
            result = output_model.model_validate_json(raw_output)
            if validate is not None:
                validate(result)
            return result
        except (ValidationError, ValueError, TypeError) as exc:
            raise AgentLlmError("AGENT_OUTPUT_INVALID", str(exc), _redact_preview(raw_output)) from exc


def _redact_preview(value: str) -> str:
    """失败记录只保留有限长度，降低模型意外回显敏感文本的风险。"""

    return value[:1000].replace("Bearer ", "Bearer ***")
