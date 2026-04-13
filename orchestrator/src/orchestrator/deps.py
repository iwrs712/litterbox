from __future__ import annotations

from fastapi import WebSocket, status

from orchestrator.auth import is_websocket_authorized, normalize_configured_token
from orchestrator.container import Container


def get_container() -> Container:
    from orchestrator.main import app  # local import to avoid circular dependency
    return app.state.container


async def require_websocket_auth(websocket: WebSocket, container: Container) -> bool:
    expected_token = normalize_configured_token(container.settings.auth.bearer_token)
    authorized = is_websocket_authorized(
        expected_token,
        websocket.headers.get("authorization"),
        websocket.query_params.get("token"),
    )
    if authorized:
        return True
    await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="unauthorized")
    return False
