from __future__ import annotations

from orchestrator.config import Settings


def test_workspace_default_size_is_one_gib() -> None:
    assert Settings().workspace.default_size == "1Gi"
