from __future__ import annotations

from orchestrator.container import Container


def get_container() -> Container:
    from orchestrator.main import app  # local import to avoid circular dependency
    return app.state.container
