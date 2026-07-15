from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


def success_response(
    data: Any,
    request_id: str,
    message: str = "操作成功",
    status_code: int = 200,
) -> JSONResponse:
    """构造统一成功响应。"""

    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder({"data": data, "message": message, "requestId": request_id}),
    )


def error_response(
    code: str,
    message: str,
    request_id: str,
    status_code: int,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    """构造统一错误响应。"""

    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(
            {
                "code": code,
                "message": message,
                "details": details or {},
                "requestId": request_id,
            }
        ),
    )
