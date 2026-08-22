"""DEM Comparator plugin entry point.

Loads metadata.txt and exposes the ``classFactory`` callable required by QGIS.
"""
from __future__ import annotations

import os


def classFactory(iface):  # noqa: D401 - QGIS plugin contract
    """QGIS plugin entry point.

    :param iface: QgisInterface instance provided by QGIS.
    :returns: An instance of the plugin's main class.
    """
    # Local import to avoid loading PyQt/QGIS at module import time
    # (QGIS imports the package before ``classFactory`` is called).
    from .plugin import DEMComparatorPlugin

    return DEMComparatorPlugin(iface)


# Metadata is read by QGIS directly from ``metadata.txt``;
# exposing a couple of commonly-used fields as attributes helps
# when the plugin is imported from Python (tests, packaging, etc.).
_PLUGIN_DIR = os.path.dirname(__file__)


def plugin_dir() -> str:
    """Return the absolute path of the plugin directory."""
    return _PLUGIN_DIR


__all__ = ["classFactory", "plugin_dir"]
