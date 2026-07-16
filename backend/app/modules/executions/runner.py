"""带网络边界校验的 HTTP Runner。"""

from dataclasses import dataclass
from time import perf_counter
from urllib.parse import urlparse

import httpx

from app.common.network import ApprovedHttpTarget, NetworkTargetError, approve_http_target, validate_stable_dns
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
) -> ApprovedHttpTarget:
    """先校验环境和 Host，再做 DNS 解析，阻断 SSRF 的常见入口。"""

    parsed = urlparse(request.url)
    if environment.environment_type == EnvironmentType.PRODUCTION:
        raise RunnerError(ExecutionErrorCategory.SECURITY, "EXECUTION_PRODUCTION_FORBIDDEN", "生产环境禁止执行")
    if request.method in _WRITE_METHODS:
        if not environment.allow_write_requests:
            raise RunnerError(ExecutionErrorCategory.SECURITY, "EXECUTION_WRITE_FORBIDDEN", "当前环境禁止写请求")
        if not write_confirmed or confirmed_host != _display_host(parsed):
            raise RunnerError(ExecutionErrorCategory.SECURITY, "EXECUTION_WRITE_CONFIRMATION_REQUIRED", "写请求需要确认当前目标 Host")
    try:
        return await approve_http_target(request.url, environment.host_allowlist)
    except NetworkTargetError as exc:
        raise _to_runner_error(exc) from exc


async def send_request(request: BuiltRequest, settings: Settings, target: ApprovedHttpTarget) -> HttpExecutionResult:
    """禁用自动重定向并限制连接数和响应体大小。"""

    timeout = httpx.Timeout(settings.default_request_timeout_seconds)
    limits = httpx.Limits(max_connections=settings.execution_max_concurrency, max_keepalive_connections=settings.execution_max_concurrency)
    try:
        await validate_stable_dns(target)
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
    except NetworkTargetError as exc:
        raise _to_runner_error(exc) from exc
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


def _display_host(parsed: object) -> str:
    parsed_url = parsed if hasattr(parsed, "netloc") else urlparse("")
    return f"{parsed_url.scheme}://{parsed_url.netloc}"


def _is_tls_error(exc: httpx.ConnectError) -> bool:
    return "ssl" in str(exc.__cause__ or exc).lower() or "tls" in str(exc.__cause__ or exc).lower()


def _to_runner_error(exc: NetworkTargetError) -> RunnerError:
    errors = {
        "invalid": (ExecutionErrorCategory.SECURITY, "EXECUTION_TARGET_INVALID", "执行目标无效"),
        "host_not_allowed": (ExecutionErrorCategory.SECURITY, "EXECUTION_HOST_NOT_ALLOWED", "目标 Host 不在白名单中"),
        "private_address": (ExecutionErrorCategory.SECURITY, "EXECUTION_PRIVATE_ADDRESS_FORBIDDEN", "目标地址不允许访问"),
        "dns_rebinding": (ExecutionErrorCategory.SECURITY, "EXECUTION_DNS_REBINDING_FORBIDDEN", "目标 DNS 解析结果发生变化"),
        "dns_empty": (ExecutionErrorCategory.DNS, "EXECUTION_DNS_EMPTY", "目标 Host 没有可用地址"),
        "dns_failed": (ExecutionErrorCategory.DNS, "EXECUTION_DNS_FAILED", "无法解析目标 Host"),
        "dns_invalid": (ExecutionErrorCategory.DNS, "EXECUTION_DNS_INVALID", "目标 Host 解析结果无效"),
    }
    category, code, message = errors.get(exc.reason, errors["invalid"])
    return RunnerError(category, code, message)
