from contextvars import ContextVar


request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """获取当前请求标识。"""

    return request_id_context.get()
