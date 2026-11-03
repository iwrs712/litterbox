from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from orchestrator.container import Container
from orchestrator.deps import get_container
from orchestrator.responses import error, ok
from orchestrator.services.metrics import sandbox_metrics

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])


@router.get("/snapshot")
def get_metrics_snapshot(container: Annotated[Container, Depends(get_container)]) -> JSONResponse:
    """返回沙盒创建指标快照（供前端 dashboard 轮询，JSON 格式）。"""
    try:
        sandbox_metrics.set_live_stats(container.sandbox_service.status_counts())
        return ok(data=sandbox_metrics.snapshot())
    except Exception as exc:  # noqa: BLE001
        return error(str(exc), 500)
