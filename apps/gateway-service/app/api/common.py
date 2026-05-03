from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from fastapi.responses import JSONResponse


def now_timestamp_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def canonical_success(data: Any, request_id: str, *, status_code: int = 200, message: str = "ok") -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "code": 0,
            "message": message,
            "request_id": request_id,
            "timestamp": now_timestamp_ms(),
            "data": data,
        },
    )


def canonical_error(
    *,
    request_id: str,
    status_code: int,
    code: int,
    message: str,
    error: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={
            "code": code,
            "message": message,
            "request_id": request_id,
            "timestamp": now_timestamp_ms(),
            "data": None,
            "error": error or {"code": code, "message": message},
        },
    )


def paginated_data(items: list[dict], *, page: int, page_size: int) -> dict[str, Any]:
    total = len(items)
    start = max(page - 1, 0) * page_size
    end = start + page_size
    return {
        "items": items[start:end],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": math.ceil(total / page_size) if page_size else 0,
    }
