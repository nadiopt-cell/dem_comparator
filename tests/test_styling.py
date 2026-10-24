"""Tests for difference-raster styling — need real QGIS + GDAL.

``diff_bound`` (pure math) is also tested in stub mode, because it lives
in a module that imports QGIS at import time.
"""
from __future__ import annotations

import pytest

from conftest import HAVE_QGIS  # noqa: F401  (ensures stubs load first)

# The pure helper can be exercised with stubs too:
from dem_comparator.core.styling import diff_bound  # noqa: E402


def test_diff_bound_symmetric_and_nan_safe():
    assert diff_bound(-3.0, 4.0) == 4.0          # max of |min|, |max|
    assert diff_bound(-5.0, 1.0) == 5.0
    assert diff_bound(float("nan"), float("nan")) == 1.0   # NaN → fallback
    assert diff_bound(0.0, 0.0) == 1.0                     # degenerate → fallback


def test_diff_bound_finite_only():
    assert diff_bound(float("nan"), 2.0) == 2.0


# ------------------------------------------------------------- real renderer
def test_apply_diff_renderer(tmp_path, require_qgis, require_gdal):
    from osgeo import gdal, osr

    from qgis.core import (
        QgsRasterLayer,
        QgsColorRampShader,
        QgsSingleBandPseudoColorRenderer,
    )

    from dem_comparator.core.styling import apply_diff_renderer

    gdal.UseExceptions()

    # Write a tiny diff raster (values −10…+5, nodata −9999).
    arr = __import__("numpy").full((4, 4), 1.0)
    arr[0, 0] = -10.0
    arr[3, 3] = 5.0
    driver = gdal.GetDriverByName("GTiff")
    path = str(tmp_path / "diff.tif")
    ds = driver.Create(path, 4, 4, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((30.0, 0.01, 0, 60.0, 0, -0.01))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-9999.0)
    band.WriteArray(arr)
    band.FlushCache()
    ds = None

    layer = QgsRasterLayer(path, "diff")
    assert layer.isValid()

    apply_diff_renderer(layer, -10.0, 5.0)

    renderer = layer.renderer()
    assert isinstance(renderer, QgsSingleBandPseudoColorRenderer)

    shader_fn = renderer.shader().rasterShaderFunction()
    assert isinstance(shader_fn, QgsColorRampShader)
    assert shader_fn.colorRampType() == QgsColorRampShader.Interpolated

    items = shader_fn.colorRampItemList()
    assert len(items) == 3
    # Symmetric ramp: negative stop mirrors the largest |value| (10), not 5.
    assert items[0].value == pytest.approx(-10.0)
    assert items[1].value == pytest.approx(0.0)
    assert items[2].value == pytest.approx(10.0)
