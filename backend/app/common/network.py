"""受控 HTTP 目标校验。"""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import ParseResult, urlparse


@dataclass(frozen=True)
class ApprovedHttpTarget:
    """已通过白名单和 DNS 校验的 HTTP 目标。"""

    parsed: ParseResult
    hostname: str
    resolved_addresses: frozenset[str]


class NetworkTargetError(Exception):
    """调用方转换为各自稳定业务错误码的网络目标错误。"""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


async def approve_http_target(url: str, allowlist: list[str]) -> ApprovedHttpTarget:
    """校验 HTTP URL、Host 白名单和首次 DNS 解析结果。"""

    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise NetworkTargetError("invalid") from exc
    if parsed.scheme not in {"http", "https"} or hostname is None or parsed.username is not None or parsed.password is not None:
        raise NetworkTargetError("invalid")
    if not is_host_allowed(hostname, allowlist):
        raise NetworkTargetError("host_not_allowed")
    return ApprovedHttpTarget(parsed=parsed, hostname=hostname, resolved_addresses=await resolve_public_addresses(hostname))


async def validate_stable_dns(target: ApprovedHttpTarget) -> None:
    """发送前再次解析，拒绝解析结果变化或指向非公网地址的目标。"""

    if await resolve_public_addresses(target.hostname) != target.resolved_addresses:
        raise NetworkTargetError("dns_rebinding")


def is_host_allowed(hostname: str, allowlist: list[str]) -> bool:
    """支持精确 Host 与单层以上的通配 Host。"""

    normalized_host = hostname.rstrip(".").lower()
    for item in allowlist:
        candidate = item.strip().rstrip(".").lower()
        if candidate.startswith("*.") and normalized_host.endswith(candidate[1:]) and normalized_host != candidate[2:]:
            return True
        if normalized_host == candidate:
            return True
    return False


def validate_host_allowlist(allowlist: list[str]) -> list[str]:
    """拒绝 URL、路径和空白项，避免把白名单误配为可注入的 URL。"""

    values: list[str] = []
    for item in allowlist:
        candidate = item.strip().rstrip(".").lower()
        if not candidate or "://" in candidate or "/" in candidate or "@" in candidate:
            raise NetworkTargetError("invalid_allowlist")
        hostname = candidate[2:] if candidate.startswith("*.") else candidate
        if not hostname or "*" in hostname:
            raise NetworkTargetError("invalid_allowlist")
        values.append(candidate)
    return values


async def resolve_public_addresses(hostname: str) -> frozenset[str]:
    """解析并拒绝回环、私网、链路本地和保留地址。"""

    try:
        records = await asyncio.get_running_loop().getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise NetworkTargetError("dns_failed") from exc
    addresses = frozenset(record[4][0] for record in records)
    if not addresses:
        raise NetworkTargetError("dns_empty")
    try:
        if any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise NetworkTargetError("private_address")
    except ValueError as exc:
        raise NetworkTargetError("dns_invalid") from exc
    return addresses
