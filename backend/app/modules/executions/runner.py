"""带网络边界校验的 HTTP Runner。"""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from time import perf_counter
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.modules.environments.models import EnvironmentType, TestEnvironment
from app.modules.executions.models import ExecutionErrorCategory
from app.modules.executions.variables import BuiltRequest

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True)
class HttpExecutionResult:
    """受大小限制的 HTTP 响应。"""

    status_code: int
    headers: dict[str, str]
    body_text: str
    duration_ms: int


class RunnerError(Exception):
    """向执行记录提供稳定错误分类。"""

    def __init__(self, category: ExecutionErrorCategory, code: str, message: str) -> None:
        self.category = category
        self.code = code
        self.message = message
        super().__init__(message)


async def validate_execution_target(
    environment: TestEnvironment,
    request: BuiltRequest,
    write_confirmed: bool,
    confirmed_host: str | None,
) -> None:
    """先校验环境和 Host，再做 DNS 解析，阻断 SSRF 的常见入口。"""

    parsed = urlparse(request.url)
    hostname = parsed.hostname
    if hostname is None:
        raise RunnerError(ExecutionErrorCategory.SECURITY, "EXECUTION_TARGET_INVALID", "执行目标无效")
    if environment.environment_type == EnvironmentType.PRODUCTION:
        raise RunnerError(ExecutionErrorCategory.SECURITY, "EXECUTION_PRODUCTION_FORBIDDEN", "生产环境禁止执行")
    if not _host_allowed(hostname, environment.host_allowlist):
        raise RunnerError(ExecutionErrorCategory.SECURITY, "EXECUTION_HOST_NOT_ALLOWED", "目标 Host 不在白名单中")
    if request.method in _WRITE_METHODS:
        if not environment.allow_write_requests:
            raise RunnerError(ExecutionErrorCategory.SECURITY, "EXECUTION_WRITE_FORBIDDEN", "当前环境禁止写请求")
        if not write_confirmed or confirmed_host != _display_host(parsed):
            raise RunnerError(ExecutionErrorCategory.SECURITY, "EXECUTION_WRITE_CONFIRMATION_REQUIRED", "写请求需要确认当前目标 Host")
    await _validate_public_dns(hostname)


async def send_request(request: BuiltRequest, settings: Settings) -> HttpExecutionResult:
    """禁用自动重定向并限制连接数和响应体大小。"""

    timeout = httpx.Timeout(settings.default_request_timeout_seconds)
    limits = httpx.Limits(max_connections=settings.execution_max_concurrency, max_keepalive_connections=settings.execution_max_concurrency)
    try:
        async with httpx.AsyncClient(timeout=timeout, limits=limits, follow_redirects=False) as client:
            started = perf_counter()
            async with client.stream(
                request.method,
                request.url,
                params=request.query,
                headers=request.headers,
                json=request.json_body,
                content=request.text_body,
            ) as response:
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > settings.max_response_body_bytes:
                        raise RunnerError(
                            ExecutionErrorCategory.RESPONSE_TOO_LARGE,
                            "EXECUTION_RESPONSE_TOO_LARGE",
                            "响应体超过大小限制",
                        )
                duration_ms = round((perf_counter() - started) * 1000)
                return HttpExecutionResult(
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    body_text=content.decode(response.encoding or "utf-8", errors="replace"),
                    duration_ms=duration_ms,
                )
    except RunnerError:
        raise
    except httpx.ConnectTimeout as exc:
        raise RunnerError(ExecutionErrorCategory.TIMEOUT, "EXECUTION_CONNECT_TIMEOUT", "连接超时") from exc
    except httpx.ReadTimeout as exc:
        raise RunnerError(ExecutionErrorCategory.TIMEOUT, "EXECUTION_READ_TIMEOUT", "响应超时") from exc
    except httpx.ConnectError as exc:
        category = ExecutionErrorCategory.TLS if _is_tls_error(exc) else ExecutionErrorCategory.CONNECTION
        code = "EXECUTION_TLS_ERROR" if category == ExecutionErrorCategory.TLS else "EXECUTION_CONNECTION_ERROR"
        message = "TLS 连接失败" if category == ExecutionErrorCategory.TLS else "连接目标服务失败"
        raise RunnerError(category, code, message) from exc
    except httpx.HTTPError as exc:
        raise RunnerError(ExecutionErrorCategory.CONNECTION, "EXECUTION_HTTP_ERROR", "HTTP 请求失败") from exc


def _host_allowed(hostname: str, allowlist: list[str]) -> bool:
    normalized_host = hostname.rstrip(".").lower()
    for item in allowlist:
        candidate = item.strip().rstrip(".").lower()
        if candidate.startswith("*.") and normalized_host.endswith(candidate[1:]) and normalized_host != candidate[2:]:
            return True
        if normalized_host == candidate:
            return True
    return False


async def _validate_public_dns(hostname: str) -> None:
    """每次请求前解析并拒绝内网、回环及保留地址，降低 DNS Rebinding 风险。"""

    try:
        records = await asyncio.get_running_loop().getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise RunnerError(ExecutionErrorCategory.DNS, "EXECUTION_DNS_FAILED", "无法解析目标 Host") from exc
    addresses = {record[4][0] for record in records}
    if not addresses:
        raise RunnerError(ExecutionErrorCategory.DNS, "EXECUTION_DNS_EMPTY", "目标 Host 没有可用地址")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise RunnerError(ExecutionErrorCategory.SECURITY, "EXECUTION_PRIVATE_ADDRESS_FORBIDDEN", "目标地址不允许访问")


def _display_host(parsed: object) -> str:
    parsed_url = parsed if hasattr(parsed, "netloc") else urlparse("")
    return f"{parsed_url.scheme}://{parsed_url.netloc}"


def _is_tls_error(exc: httpx.ConnectError) -> bool:
    return "ssl" in str(exc.__cause__ or exc).lower() or "tls" in str(exc.__cause__ or exc).lower()
