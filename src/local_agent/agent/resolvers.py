"""Resolve numbered references (序号), UUID prefix, or full ID."""

from __future__ import annotations

from typing import Callable, TypeVar

T = TypeVar("T")


def resolve_ref(
    items: list[T],
    ref: str,
    get_id: Callable[[T], str],
) -> T | None:
    """Match *ref* against a numbered list (1-based), full ID, or unique prefix."""
    ref = ref.strip()
    if not ref:
        return None

    if ref.isdigit():
        idx = int(ref)
        if 1 <= idx <= len(items):
            return items[idx - 1]
        return None

    for item in items:
        if get_id(item) == ref:
            return item

    matches = [item for item in items if get_id(item).startswith(ref)]
    if len(matches) == 1:
        return matches[0]
    return None
