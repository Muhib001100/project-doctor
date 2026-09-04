"""Check registry.

A check is a callable ``(project, ctx) -> Iterable[Finding]`` registered with an
id, a human name and a category. Add a module here and it shows up in the CLI.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Callable, NamedTuple

from ..model import Finding, Project

CheckFn = Callable[[Project, dict], Iterable[Finding]]


class Check(NamedTuple):
    id: str
    name: str
    description: str
    fn: CheckFn
    network: bool = False


_REGISTRY: dict[str, Check] = {}


def register(id: str, name: str, description: str, network: bool = False):
    def deco(fn: CheckFn) -> CheckFn:
        if id in _REGISTRY:
            raise ValueError(f"duplicate check id: {id}")
        _REGISTRY[id] = Check(id, name, description, fn, network)
        return fn
    return deco


def all_checks() -> list[Check]:
    from . import (  # noqa: F401  (import for side effects)
        ci,
        config,
        dependencies,
        docs,
        outdated,
        quality,
        tests,
    )
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def get(id: str) -> Check | None:
    all_checks()
    return _REGISTRY.get(id)
