"""Artifact file preview helpers (API re-exports)."""

from local_agent.artifacts.file_preview import (
    build_preview,
    build_spreadsheet_preview as _build_spreadsheet_preview,
    build_table_preview as _build_table_preview,
    preview_kind,
)

__all__ = [
    "build_preview",
    "preview_kind",
    "_build_spreadsheet_preview",
    "_build_table_preview",
]
