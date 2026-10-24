# -*- coding: utf-8 -*-
"""Minimal stub — Qt resource module.

The plugin loads its icon from the filesystem (``icons/icon.png``),
so the compiled resource module is not required. This stub ensures
compatibility with QGIS plugin conventions that expect the module
to exist when ``resources.qrc`` is present.
"""

from __future__ import annotations


def qInitResources() -> None:
    """No-op — resources are not embedded."""
    pass


def qCleanupResources() -> None:
    """No-op — resources are not embedded."""
    pass


__all__ = ["qInitResources", "qCleanupResources"]
