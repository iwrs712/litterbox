from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from orchestrator.domain.models import ApiResponse


def ok(*, data=None, message: str | None = None, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ApiResponse(success=True, data=data, message=message).model_dump(mode="json", exclude_none=True),
    )


def error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ApiResponse(success=False, error=message).model_dump(mode="json", exclude_none=True),
    )


def parse_timeout(timeout: str | None) -> int:
    if not timeout:
        return 10
    try:
        if timeout.endswith("s"):
            value = int(timeout[:-1])
        elif timeout.endswith("m"):
            value = int(timeout[:-1]) * 60
        elif timeout.endswith("h"):
            value = int(timeout[:-1]) * 3600
        else:
            value = int(timeout)
        return max(1, min(value, 3600))
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="invalid timeout format, use e.g. 30s, 5m, 1h")
