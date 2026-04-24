from __future__ import annotations

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
