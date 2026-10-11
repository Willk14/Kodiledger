"""Backward-compatible imports; configuration lives in :mod:`app.configs`."""

from app.configs.environment import Settings, settings

__all__ = ["Settings", "settings"]
