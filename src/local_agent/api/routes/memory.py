"""Memory API routes (Phase 2 skeleton)."""

from __future__ import annotations

ROUTES = [
    ("GET", "/api/v1/agents/{id}/memory", "get_memory"),
    ("GET", "/api/v1/agents/{id}/canvas", "get_canvas"),
]
