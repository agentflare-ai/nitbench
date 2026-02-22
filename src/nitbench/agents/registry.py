"""Simple adapter registry with ``@register`` decorator."""

from __future__ import annotations

from typing import Optional, Type

from nitbench.agents.base import AgentAdapter

_REGISTRY: dict[str, Type[AgentAdapter]] = {}


def register(cls: Type[AgentAdapter]) -> Type[AgentAdapter]:
    """Class decorator that registers an adapter by its ``agent_family``."""
    _REGISTRY[cls.agent_family] = cls
    return cls


def get_adapter(family: str) -> Optional[AgentAdapter]:
    """Return an instance of the adapter for *family*, or ``None``."""
    cls = _REGISTRY.get(family)
    if cls is None:
        return None
    return cls()


def registered_families() -> list[str]:
    """Return the list of registered agent family names."""
    return list(_REGISTRY.keys())
