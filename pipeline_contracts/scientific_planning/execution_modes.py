"""Explicit mapping between Planning Core backend ids and Agent A execution modes."""
from __future__ import annotations

from typing import Any


_BACKEND_TO_AGENT_A_MODE = {
    "mock": "mock",
    "cp2k": "real",
}


def agent_a_execution_mode(backend: Any) -> str | None:
    """Map a registered backend to Agent A's mode; never infer unknown backends."""
    if not isinstance(backend, str):
        return None
    token = backend.strip().casefold()
    if not token:
        return None
    return _BACKEND_TO_AGENT_A_MODE.get(token)


__all__ = ["agent_a_execution_mode"]
