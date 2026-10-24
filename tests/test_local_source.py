"""Tests for local DEM file sources (issue #4)."""
from __future__ import annotations

import os

import pytest

from dem_comparator.sources.local import (
    LocalDEMSource,
    _base_id,
    assign_local_ids,
)


def test_base_id_sanitizes_names():
    assert _base_id("/any/dir/My Dem (2024).tif") == "My_Dem_2024"
    assert _base_id("/x/y/....tif") == "tif"          # leading dots collapse
    assert _base_id("/x/_.tif") == "local_dem"        # empty stem → fallback
    assert _base_id("plain_name.TIF") == "plain_name"


def test_assign_local_ids_unique_for_same_basename():
    ids = assign_local_ids(["/a/dem.tif", "/b/dem.tif"])
    assert list(ids.values()) == ["dem", "dem_2"]


def test_assign_local_ids_deterministic_and_unique():
    paths = ["/x/one.tif", "/x/two.tif", "/x/ONE (copy).tif"]
    ids = assign_local_ids(paths)
    assert ids == assign_local_ids(paths)          # deterministic
    assert len(set(ids.values())) == len(paths)    # unique within a run


def test_local_source_metadata(tmp_path):
    f = tmp_path / "lidar_dtm.tif"
    f.write_bytes(b"stub")
    src = LocalDEMSource(str(f), source_id="lidar_dtm", cache_dir=str(tmp_path / "cache"))
    assert src.id == "lidar_dtm"
    assert src.name == "lidar_dtm.tif"
    assert src.vertical_datum == ""          # unknown datum -> "unspecified"
    assert src.dem_type == "unknown"
    assert src.is_available(None) is True


def test_local_source_missing_file(tmp_path):
    src = LocalDEMSource(
        str(tmp_path / "nope.tif"), source_id="x", cache_dir=str(tmp_path)
    )
    assert src.is_available(None) is False
    assert "not found" in src.unavailable_reason(None)


def test_download_cancelled_before_start(tmp_path):
    from dem_comparator.core.orchestrator import OrchestratorCancelled

    src = LocalDEMSource(
        str(tmp_path / "f.tif"), source_id="f", cache_dir=str(tmp_path)
    )
    with pytest.raises(OrchestratorCancelled):
        src.download(None, str(tmp_path / "out.tif"), is_cancelled=lambda: True)


def test_download_missing_file_raises_runtimeerror(tmp_path, require_gdal):
    src = LocalDEMSource(
        str(tmp_path / "missing.tif"), source_id="m", cache_dir=str(tmp_path)
    )
    with pytest.raises(RuntimeError):
        src.download(None, str(tmp_path / "out.tif"))


def test_download_clips_and_reprojects(tmp_path, require_gdal):
    """A real GeoTIFF in a projected CRS is warped to EPSG:4326 + clipped."""
    import numpy as np
    from osgeo import gdal, osr

    gdal.UseExceptions()
    osr.UseExceptions()

    # 1 m source raster in UTM 37N (EPSG:32637): 100x100 px, heights 0..99.
    src_path = str(tmp_path / "utm_dem.tif")
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32637)
    # GDAL 3 honours the authority axis order (EPSG:4326 = lat, lon);
    # force traditional lon/lat order for TransformPoint below.
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(src_path, 100, 100, 1, gdal.GDT_Float32)
    ds.SetProjection(srs.ExportToWkt())
    ds.SetGeoTransform((500000.0, 1.0, 0.0, 5_000_000.0, 0.0, -1.0))
    ds.GetRasterBand(1).WriteArray(
        np.arange(10_000, dtype=np.float32).reshape(100, 100)
    )
    ds = None

    # AOI: a small box around the raster centre, expressed in EPSG:4326.
    from qgis.core import QgsCoordinateReferenceSystem, QgsRectangle

    from dem_comparator.core.extent_utils import ExtentInfo

    # centre of the UTM raster -> lon/lat
    srs_wgs = osr.SpatialReference()
    srs_wgs.ImportFromEPSG(4326)
    srs_wgs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    tr = osr.CoordinateTransformation(srs, srs_wgs)
    lon_c, lat_c, _ = tr.TransformPoint(500050.0, 4999950.0)
    pad = 0.001
    extent = ExtentInfo(
        QgsRectangle(lon_c - pad, lat_c - pad, lon_c + pad, lat_c + pad),
        QgsCoordinateReferenceSystem("EPSG:4326"),
    )

    src = LocalDEMSource(src_path, source_id="u", cache_dir=str(tmp_path))
    out = str(tmp_path / "out.tif")
    result = src.download(extent, out)

    assert result == out and os.path.exists(out)
    chk = gdal.Open(out)
    wkt = chk.GetSpatialRef().ExportToWkt()
    assert "WGS 84" in wkt or "4326" in wkt
    assert chk.RasterXSize > 0 and chk.RasterYSize > 0
    mn, mx, _, _ = chk.GetRasterBand(1).GetStatistics(True, True)
    assert mx > mn, "clipped raster must contain data, not only nodata"
    chk = None


def test_download_outside_aoi_raises(tmp_path, require_gdal):
    """A raster that does not intersect the AOI fails with a clear error."""
    import numpy as np
    from osgeo import gdal, osr

    gdal.UseExceptions()

    src_path = str(tmp_path / "far_dem.tif")
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(src_path, 10, 10, 1, gdal.GDT_Float32)
    ds.SetProjection(srs.ExportToWkt())
    ds.SetGeoTransform((10.0, 0.01, 0.0, 20.0, 0.0, -0.01))  # lon 10-10.1, lat 19.9-20
    ds.GetRasterBand(1).WriteArray(np.ones((10, 10), dtype=np.float32) * 5)
    ds = None

    from qgis.core import QgsCoordinateReferenceSystem, QgsRectangle

    from dem_comparator.core.extent_utils import ExtentInfo

    extent = ExtentInfo(
        QgsRectangle(30.0, 50.0, 30.1, 50.1),  # far away
        QgsCoordinateReferenceSystem("EPSG:4326"),
    )

    src = LocalDEMSource(src_path, source_id="far", cache_dir=str(tmp_path))
    out = str(tmp_path / "out.tif")
    with pytest.raises(RuntimeError, match="does not intersect|no valid pixels"):
        src.download(extent, out)
