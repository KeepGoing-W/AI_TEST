from typing import Annotated
from urllib.parse import urlparse
from uuid import UUID

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import AppError
from app.common.responses import success_response
from app.config import get_settings
from app.database import get_db_session
from app.modules.auth.dependencies import require_admin
from app.modules.llm_configs.models import LlmConfig

router = APIRouter(prefix="/llm-configs", tags=["LLM 配置"])


class LlmConfigRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    provider: str = Field(min_length=1, max_length=64)
    base_url: str
    model: str = Field(min_length=1, max_length=256)
    api_key: str = Field(min_length=1)
    context_window: int = Field(gt=0)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_output_tokens: int = Field(gt=0)
    is_default: bool = False
    enabled: bool = True


def cipher() -> Fernet:
    try:
        return Fernet(get_settings().encryption_key.get_secret_value())
    except (TypeError, ValueError) as exc:
        raise AppError("ENCRYPTION_KEY_INVALID", "加密配置无效", 500) from exc


def response_item(item: LlmConfig) -> dict[str, object]:
    return {"id": item.id, "name": item.name, "provider": item.provider, "baseUrl": item.base_url, "model": item.model, "contextWindow": item.context_window, "temperature": item.temperature, "maxOutputTokens": item.max_output_tokens, "isDefault": item.is_default, "enabled": item.enabled, "apiKeyConfigured": True}


@router.post("")
async def create_config(payload: LlmConfigRequest, request: Request, _: Annotated[object, Depends(require_admin)], session: Annotated[AsyncSession, Depends(get_db_session)]) -> Response:
    if urlparse(payload.base_url).scheme not in {"http", "https"}:
        raise AppError("LLM_BASE_URL_INVALID", "LLM Base URL 无效", 400)
    if payload.is_default:
        await session.execute(update(LlmConfig).values(is_default=False))
    item = LlmConfig(**payload.model_dump(exclude={"api_key"}), encrypted_api_key=cipher().encrypt(payload.api_key.encode()).decode())
    session.add(item)
    await session.commit(); await session.refresh(item)
    return success_response(data=response_item(item), request_id=request.state.request_id, status_code=201)


@router.get("")
async def list_configs(request: Request, _: Annotated[object, Depends(require_admin)], session: Annotated[AsyncSession, Depends(get_db_session)]) -> Response:
    values = await session.scalars(select(LlmConfig).order_by(LlmConfig.created_at.desc()))
    return success_response(data=[response_item(item) for item in values], request_id=request.state.request_id)


@router.post("/{config_id}/test")
async def test_config(config_id: UUID, request: Request, _: Annotated[object, Depends(require_admin)], session: Annotated[AsyncSession, Depends(get_db_session)]) -> Response:
    item = await session.get(LlmConfig, config_id)
    if item is None:
        raise AppError("LLM_CONFIG_NOT_FOUND", "LLM 配置不存在", 404)
    try:
        api_key = cipher().decrypt(item.encrypted_api_key.encode()).decode()
        async with httpx.AsyncClient(timeout=10) as client:
            result = await client.get(f"{item.base_url.rstrip('/')}/models", headers={"Authorization": f"Bearer {api_key}"})
        success = result.is_success
    except (httpx.HTTPError, InvalidToken):
        success = False
    return success_response(data={"success": success}, request_id=request.state.request_id)
