"""Custom checks, registered by `custom_id`.

A check is a function ``fn(env: Env) -> list[dict]`` returning findings (see bimcheck.engine.finding.Env).
Register with ``@register("my_custom_id")``. Unknown ids are handled by the runner (single `review` finding).
"""
from __future__ import annotations

from typing import Callable

REGISTRY: dict[str, Callable] = {}


def register(custom_id: str):
    def deco(fn):
        REGISTRY[custom_id] = fn
        fn.custom_id = custom_id
        return fn
    return deco


def get(custom_id: str | None):
    _load()
    return REGISTRY.get(custom_id or "")


_loaded = False


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    from . import (circulation, drawing, elevator, gardenwall, heights, lightwell, openings, rooms,  # noqa: F401
                   site, stairs)


def available() -> list[str]:
    _load()
    return sorted(REGISTRY)
