"""Shared pytest configuration for DEM Comparator tests.

Two goals:

1. Make the plugin package importable (repo root on ``sys.path``).
2. When the QGIS / GDAL Python bindings are missing (plain CI, dev
   laptop), install *minimal import-time stubs* so that the pure-logic
   test modules (``test_pc_client``, ``test_report``, ``test_metadata``,
   ``test_sources_base``) can still import and exercise the plugin code.

The stubs are intentionally dumb: they only make ``import`` succeed.
Tests that exercise real raster machinery (``test_compare``,
``test_align``, ``test_styling``) check :data:`HAVE_GDAL` /
:data:`HAVE_QGIS` via the ``require_gdal`` / ``require_qgis`` fixtures
and skip when the real bindings are not present.
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# --------------------------------------------------------------------------
# Real-availability detection (before any stubbing).
# --------------------------------------------------------------------------
try:  # pragma: no cover - depends on environment
    import qgis  # noqa: F401
    HAVE_QGIS = True
except Exception:
    HAVE_QGIS = False

try:  # pragma: no cover - depends on environment
    from osgeo import gdal  # noqa: F401
    HAVE_GDAL = True
except Exception:
    HAVE_GDAL = False

STUBBED = False

# --------------------------------------------------------------------------
# Minimal stubs (only when the real bindings are absent).
# --------------------------------------------------------------------------
if not HAVE_QGIS:  # pragma: no cover - exercised only without QGIS
    STUBBED = True
    os.environ["DEM_COMPARATOR_TEST_STUBS"] = "1"

    class _StubCRS:
        """Stub for QgsCoordinateReferenceSystem.

        Compares equal to every other stub CRS so that
        ``ExtentInfo.transformed`` short-circuits ("already in target CRS")
        instead of needing a real coordinate transform.
        """

        def __init__(self, *args, **kwargs):
            self._authid = args[0] if args else "EPSG:4326"

        def authid(self):
            return self._authid

        def isValid(self):  # noqa: N802 - QGIS API shape
            return True

        def __eq__(self, other):  # noqa: D105
            return isinstance(other, _StubCRS)

        def __hash__(self):  # noqa: D105
            return hash(_StubCRS)

    class _StubRectangle:
        """Stub for QgsRectangle: stores bounds, mirrors the used API."""

        def __init__(self, *args):
            if len(args) == 1 and isinstance(args[0], _StubRectangle):
                src = args[0]
                (xmin, ymin, xmax, ymax) = (
                    src._xmin, src._ymin, src._xmax, src._ymax,
                )
            elif len(args) == 4:
                xmin, ymin, xmax, ymax = args
            else:
                xmin = ymin = xmax = ymax = 0.0
            self._xmin, self._ymin = float(xmin), float(ymin)
            self._xmax, self._ymax = float(xmax), float(ymax)

        def xMinimum(self): return self._xmin  # noqa: E704
        def yMinimum(self): return self._ymin  # noqa: E704
        def xMaximum(self): return self._xmax  # noqa: E704
        def yMaximum(self): return self._ymax  # noqa: E704
        def setXMinimum(self, v): self._xmin = float(v)  # noqa: E704
        def setYMinimum(self, v): self._ymin = float(v)  # noqa: E704
        def setXMaximum(self, v): self._xmax = float(v)  # noqa: E704
        def setYMaximum(self, v): self._ymax = float(v)  # noqa: E704
        def width(self): return self._xmax - self._xmin  # noqa: E704
        def height(self): return self._ymax - self._ymin  # noqa: E704
        def toString(self):  # noqa: N802,E704
            return f"{self._xmin},{self._ymin},{self._xmax},{self._ymax}"

    class _StubAny:
        """Catch-all stub for the remaining QGIS names used at import time."""

        def __init__(self, *args, **kwargs):
            pass

        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            return _StubAny()

        def __call__(self, *args, **kwargs):
            return _StubAny()

    _qgis = types.ModuleType("qgis")
    _qgis.__path__ = []  # mark as a package so "qgis.PyQt" imports resolve
    _qgis_core = types.ModuleType("qgis.core")
    _qgis_core.QgsCoordinateReferenceSystem = _StubCRS
    _qgis_core.QgsRectangle = _StubRectangle
    for _name in (
        "QgsCoordinateTransform",
        "QgsCoordinateTransformContext",
        "QgsGeometry",
        "QgsProcessingFeedback",
        "QgsRasterLayer",
        "QgsRasterShader",
        "QgsColorRampShader",
        "QgsSingleBandPseudoColorRenderer",
        "QgsApplication",
        "QgsProject",
        "QgsSettings",
        "QgsMessageLog",
        "QgsTask",
    ):
        setattr(_qgis_core, _name, type(_name, (_StubAny,), {}))
    _qgis.core = _qgis_core
    _qgis_pyqt = types.ModuleType("qgis.PyQt")
    _qgis_pyqt.__path__ = []
    _qgis_qtcore = types.ModuleType("qgis.PyQt.QtCore")
    _qgis_qtgui = types.ModuleType("qgis.PyQt.QtGui")

    class _StubColor(_StubAny):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._name = args[0] if args else "#000000"

        def name(self):
            return self._name

    _qgis_qtgui.QColor = _StubColor
    _qgis_pyqt.QtCore = _qgis_qtcore
    _qgis_pyqt.QtGui = _qgis_qtgui
    sys.modules.setdefault("qgis", _qgis)
    sys.modules.setdefault("qgis.core", _qgis_core)
    sys.modules.setdefault("qgis.PyQt", _qgis_pyqt)
    sys.modules.setdefault("qgis.PyQt.QtCore", _qgis_qtcore)
    sys.modules.setdefault("qgis.PyQt.QtGui", _qgis_qtgui)

if not HAVE_GDAL:  # pragma: no cover - exercised only without GDAL
    STUBBED = True
    os.environ["DEM_COMPARATOR_TEST_STUBS"] = "1"

    _osgeo = types.ModuleType("osgeo")
    _gdal = types.ModuleType("osgeo.gdal")
    _osr = types.ModuleType("osgeo.osr")
    for _name in (
        "GA_ReadOnly", "GDT_Float32", "GDT_Byte",
    ):
        setattr(_gdal, _name, 0)
    _gdal.UseExceptions = lambda *a, **k: None
    _osgeo.gdal = _gdal
    _osgeo.osr = _osr
    sys.modules.setdefault("osgeo", _osgeo)
    sys.modules.setdefault("osgeo.gdal", _gdal)
    sys.modules.setdefault("osgeo.osr", _osr)


# --------------------------------------------------------------------------
# Fixtures.
# --------------------------------------------------------------------------
@pytest.fixture
def require_gdal():
    """Skip the test unless the real GDAL bindings are importable."""
    if not HAVE_GDAL:
        pytest.skip("GDAL (osgeo) bindings not available — run inside QGIS Python")


@pytest.fixture
def require_qgis():
    """Skip the test unless the real QGIS bindings are importable."""
    if not HAVE_QGIS:
        pytest.skip("QGIS Python bindings not available — run inside QGIS")


@pytest.fixture
def stub_rect():
    """A rectangle-like object that works both with real QGIS and stubs."""
    from dem_comparator.core.extent_utils import QgsRectangle

    def _make(xmin, ymin, xmax, ymax):
        return QgsRectangle(xmin, ymin, xmax, ymax)

    return _make
