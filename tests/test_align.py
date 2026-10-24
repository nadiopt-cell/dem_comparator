"""Tests for the grid aligner — need real GDAL (run inside QGIS)."""
from __future__ import annotations

import numpy as np
import pytest

from conftest import HAVE_GDAL, HAVE_QGIS  # noqa: F401  (ensures stubs load first)

if not HAVE_GDAL:
    pytest.skip("GDAL (osgeo) bindings not available", allow_module_level=True)

from osgeo import gdal, osr  # noqa: E402

from dem_comparator.core.align import Aligner, RasterSpec, NODATA, make_aligner  # noqa: E402

gdal.UseExceptions()


def _write(path: str, arr: np.ndarray, gt) -> None:
    driver = gdal.GetDriverByName("GTiff")
    rows, cols = arr.shape
    ds = driver.Create(path, cols, rows, 1, gdal.GDT_Float32)
    ds.SetGeoTransform(gt)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(NODATA)
    band.WriteArray(arr.astype(np.float32))
    band.FlushCache()
    ds = None


def _read_grid(path: str):
    ds = gdal.Open(path)
    return ds.GetGeoTransform(), ds.RasterXSize, ds.RasterYSize


def test_compute_grid_union_of_extents(tmp_path):
    """Grid extent must cover both rasters even when origins differ."""
    a_path = str(tmp_path / "a.tif")
    b_path = str(tmp_path / "b.tif")
    _write(a_path, np.zeros((10, 10)), (30.00, 0.01, 0, 60.00, 0, -0.01))
    _write(b_path, np.zeros((10, 10)), (30.05, 0.01, 0, 60.05, 0, -0.01))

    aligner = Aligner(str(tmp_path), resolution_deg=0.01)
    grid = aligner.compute_grid([
        RasterSpec("A", a_path, str(tmp_path / "a_al.tif")),
        RasterSpec("B", b_path, str(tmp_path / "b_al.tif")),
    ])

    xmin, ymin, xmax, ymax = grid.extent
    assert xmin <= 30.00 + 1e-9
    assert ymin <= 60.00 - 0.10 + 1e-9
    assert xmax >= 30.05 + 0.10 - 1e-9
    assert ymax >= 60.05 - 1e-9


def test_align_produces_identical_grids(tmp_path):
    a_path = str(tmp_path / "a.tif")
    b_path = str(tmp_path / "b.tif")
    _write(a_path, np.full((10, 10), 50.0), (30.00, 0.01, 0, 60.00, 0, -0.01))
    _write(b_path, np.full((10, 10), 45.0), (30.05, 0.01, 0, 60.05, 0, -0.01))

    aligner = Aligner(str(tmp_path), resolution_deg=0.01)
    specs = [
        RasterSpec("A", a_path, str(tmp_path / "a_al.tif")),
        RasterSpec("B", b_path, str(tmp_path / "b_al.tif")),
    ]
    grid = aligner.compute_grid(specs)
    aligner.align(specs, grid)

    gt_a, w_a, h_a = _read_grid(specs[0].output_path)
    gt_b, w_b, h_b = _read_grid(specs[1].output_path)

    assert (w_a, h_a) == (w_b, h_b)
    assert gt_a == gt_b, "both rasters must land on exactly the same grid"
    assert gt_a[1] == pytest.approx(0.01)


def test_make_aligner_converts_meters_to_degrees(tmp_path):
    aligner = make_aligner(str(tmp_path), resolution_m=30.0)
    assert aligner.resolution_deg == pytest.approx(30.0 / 111_320.0)


def test_invalid_resampling_rejected(tmp_path):
    with pytest.raises(ValueError):
        Aligner(str(tmp_path), resolution_deg=0.01, resampling="laplace")


def test_missing_input_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        RasterSpec("ghost", str(tmp_path / "missing.tif"), str(tmp_path / "o.tif"))
