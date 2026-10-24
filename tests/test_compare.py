"""Tests for the pairwise comparator — need real GDAL (run inside QGIS)."""
from __future__ import annotations

import math

import numpy as np
import pytest

from conftest import HAVE_GDAL, HAVE_QGIS  # noqa: F401  (ensures stubs load first)

if not HAVE_GDAL:
    pytest.skip("GDAL (osgeo) bindings not available", allow_module_level=True)

from osgeo import gdal, osr  # noqa: E402

from dem_comparator.core.align import NODATA  # noqa: E402
from dem_comparator.core.compare import Comparator  # noqa: E402

gdal.UseExceptions()

GT = (30.0, 0.01, 0.0, 60.0, 0.0, -0.01)  # 10x10 grid near 60N


def _write(path: str, arr: np.ndarray, nodata: float = NODATA) -> None:
    driver = gdal.GetDriverByName("GTiff")
    rows, cols = arr.shape
    ds = driver.Create(path, cols, rows, 1, gdal.GDT_Float32)
    ds.SetGeoTransform(GT)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(nodata)
    band.WriteArray(arr.astype(np.float32))
    band.FlushCache()
    ds = None


@pytest.fixture
def two_dems(tmp_path):
    """DEM A = 100 m flat; DEM B = A − 5; both with 2 masked pixels."""
    a = np.full((10, 10), 100.0)
    a[0, 0] = NODATA
    a[5, 5] = NODATA

    b = np.full((10, 10), 95.0)
    b[2, 2] = NODATA          # only B masked (still counted as invalid pair)

    pa = str(tmp_path / "a.tif")
    pb = str(tmp_path / "b.tif")
    _write(pa, a)
    _write(pb, b)
    return pa, pb


# -------------------------------------------------------------- all pairs
def test_all_pairs_stats(two_dems, tmp_path):
    pa, pb = two_dems
    result = Comparator(str(tmp_path / "diffs")).compare([("A", pa), ("B", pb)])

    assert len(result.pairs) == 1
    p = result.pairs[0]
    assert p.label_a == "A" and p.label_b == "B"

    # 100 valid pairs (one A-nodata and one B-nodata pixel each kill 1).
    assert p.valid_pixels == 98
    assert math.isclose(p.mean_bias, 5.0, rel_tol=1e-6)
    assert math.isclose(p.mae, 5.0, rel_tol=1e-6)
    assert math.isclose(p.rmse, 5.0, rel_tol=1e-6)
    assert math.isclose(p.std_dev, 0.0, abs_tol=1e-6)
    assert math.isclose(p.diff_min, 5.0, rel_tol=1e-6)
    assert math.isclose(p.diff_max, 5.0, rel_tol=1e-6)

    # Diff raster must exist with the exact pairwise naming convention.
    assert p.diff_raster.endswith("DIFF_A_minus_B.tif")


def test_diff_raster_values_and_nodata(two_dems, tmp_path):
    pa, pb = two_dems
    result = Comparator(str(tmp_path / "diffs")).compare([("A", pa), ("B", pb)])
    ds = gdal.Open(result.pairs[0].diff_raster)
    band = ds.GetRasterBand(1)
    arr = band.ReadAsArray()

    assert band.GetNoDataValue() == NODATA
    valid = arr[arr != NODATA]
    assert np.allclose(valid, 5.0)
    # The two masked pixels must be nodata in the diff too.
    assert arr[0, 0] == NODATA
    assert arr[2, 2] == NODATA
    assert arr[5, 5] == NODATA


def test_reference_mode_pair_labels(two_dems, tmp_path):
    pa, pb = two_dems
    result = Comparator(str(tmp_path / "diffs"), reference="B").compare(
        [("A", pa), ("B", pb)]
    )
    p = result.pairs[0]
    assert (p.label_a, p.label_b) == ("B", "A")
    assert math.isclose(p.mean_bias, -5.0, rel_tol=1e-6)


def test_reference_must_be_among_rasters(tmp_path):
    with pytest.raises(ValueError):
        Comparator(str(tmp_path), reference="nope").compare([])


# --------------------------------------------------------- no-overlap case
def test_zero_valid_pixels_yields_nan_stats(tmp_path):
    a = np.full((4, 4), 10.0)
    b = np.full((4, 4), 10.0)
    a[0, 0] = NODATA
    b[:] = NODATA  # B entirely masked

    pa = str(tmp_path / "a.tif")
    pb = str(tmp_path / "b.tif")
    _write(pa, a)
    _write(pb, b)

    result = Comparator(str(tmp_path / "diffs")).compare([("A", pa), ("B", pb)])
    p = result.pairs[0]
    assert p.valid_pixels == 0
    assert math.isnan(p.mean_bias)
    assert math.isnan(p.rmse)
