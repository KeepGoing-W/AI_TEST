from typing import Annotated
from urllib.parse import urlparse
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import AppError
from app.common.network import NetworkTargetError, is_host_allowed, validate_host_allowlist
from app.common.responses import success_response
from app.config import get_settings
from app.database import get_db_session
from app.modules.environments.models import EnvironmentType, EnvironmentVariable, TestEnvironment
from app.modules.projects.dependencies import AccessibleProject, CurrentAdmin

router = APIRouter(prefix="/projects/{project_id}/environments", tags=["测试环境"])


class EnvironmentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    base_url: str
    environment_type: EnvironmentType
    common_headers: dict[str, str] = Field(default_factory=dict)
    host_allowlist: list[str] = Field(default_factory=list)
    allow_write_requests: bool = False


class VariableRequest(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1)
    is_secret: bool = False


def validate_environment(payload: EnvironmentRequest) -> None:
    try:
        parsed = urlparse(payload.base_url)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise AppError("ENVIRONMENT_BASE_URL_INVALID", "Base URL 无效", 400) from exc
    if parsed.scheme not in {"http", "https"} or hostname is None or parsed.username is not None or parsed.password is not None:
        raise AppError("ENVIRONMENT_BASE_URL_INVALID", "Base URL 无效", 400)
    try:
        allowlist = validate_host_allowlist(payload.host_allowlist)
    except NetworkTargetError as exc:
        raise AppError("ENVIRONMENT_HOST_ALLOWLIST_INVALID", "Host 白名单无效", 400) from exc
    if not allowlist or not is_host_allowed(hostname, allowlist):
        raise AppError("ENVIRONMENT_BASE_URL_NOT_ALLOWED", "Base URL Host 必须在白名单中", 400)
    if payload.environment_type == EnvironmentType.PRODUCTION and payload.allow_write_requests:
        raise AppError("ENVIRONMENT_PRODUCTION_READONLY", "生产环境禁止写请求", 400)


def encrypt_value(value: str) -> str:
    try:
        return Fernet(get_settings().encryption_key.get_secret_value()).encrypt(value.encode()).decode()
    except (ValueError, TypeError) as exc:
        raise AppError("ENCRYPTION_KEY_INVALID", "加密配置无效", 500) from exc


@router.post("")
async def create_environment(payload: EnvironmentRequest, request: Request, project: AccessibleProject, _: CurrentAdmin, session: Annotated[AsyncSession, Depends(get_db_session)]) -> Response:
    validate_environment(payload)
    environment = TestEnvironment(project_id=project.id, **payload.model_dump())
    session.add(environment)
    await session.commit()
    await session.refresh(environment)
    return success_response(data={"id": environment.id, "name": environment.name}, request_id=request.state.request_id, status_code=201)


@router.get("")
async def list_environments(request: Request, project: AccessibleProject, session: Annotated[AsyncSession, Depends(get_db_session)]) -> Response:
    values = await session.scalars(select(TestEnvironment).where(TestEnvironment.project_id == project.id))
    return success_response(data=[{"id": item.id, "name": item.name, "baseUrl": item.base_url, "environmentType": item.environment_type, "allowWriteRequests": item.allow_write_requests, "hostAllowlist": item.host_allowlist} for item in values], request_id=request.state.request_id)


@router.patch("/{environment_id}")
async def update_environment(
    environment_id: UUID,
    payload: EnvironmentRequest,
    request: Request,
    project: AccessibleProject,
    _: CurrentAdmin,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    validate_environment(payload)
    environment = await session.get(TestEnvironment, environment_id)
    if environment is None or environment.project_id != project.id:
        raise AppError("ENVIRONMENT_NOT_FOUND", "测试环境不存在", 404)
    for field, value in payload.model_dump().items():
        setattr(environment, field, value)
    await session.commit()
    await session.refresh(environment)
    return success_response(
        data={
            "id": environment.id,
            "name": environment.name,
            "baseUrl": environment.base_url,
            "environmentType": environment.environment_type,
            "allowWriteRequests": environment.allow_write_requests,
            "hostAllowlist": environment.host_allowlist,
        },
        request_id=request.state.request_id,
    )


@router.put("/{environment_id}/variables")
async def set_variable(environment_id: UUID, payload: VariableRequest, request: Request, project: AccessibleProject, _: CurrentAdmin, session: Annotated[AsyncSession, Depends(get_db_session)]) -> Response:
    environment = await session.get(TestEnvironment, environment_id)
    if environment is None or environment.project_id != project.id:
        raise AppError("ENVIRONMENT_NOT_FOUND", "测试环境不存在", 404)
    variable = await session.scalar(select(EnvironmentVariable).where(EnvironmentVariable.environment_id == environment_id, EnvironmentVariable.variable_key == payload.key))
    if variable is None:
        variable = EnvironmentVariable(environment_id=environment_id, variable_key=payload.key)
        session.add(variable)
    variable.is_secret = payload.is_secret
    variable.value = None if payload.is_secret else payload.value
    variable.encrypted_value = encrypt_value(payload.value) if payload.is_secret else None
    await session.commit()
    return success_response(data={"key": variable.variable_key, "isSecret": variable.is_secret, "configured": True}, request_id=request.state.request_id)
