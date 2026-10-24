"""Tests for BaseDEMSource availability, tile cache and vertical datums.

These tests run anywhere: with real QGIS bindings or with the stubs from
conftest (the availability logic itself is pure Python + one client call).
"""
from __future__ import annotations

import os

import pytest

from conftest import HAVE_QGIS  # noqa: F401  (ensures stubs load first)

from dem_comparator.core.extent_utils import COMMON_CRS, ExtentInfo, QgsRectangle
from dem_comparator.core.pc_client import PCError, PCItem
from dem_comparator.sources.srtm import SRTMSource
from dem_comparator.sources.glo30 import GLO30Source
from dem_comparator.sources import base as base_mod


class FakeClient:
    """PlanetaryComputerClient double with a scriptable find_items."""

    user_agent = "fake-agent/1.0"

    def __init__(self, items=None, error=None):
        self._items = items or []
        self._error = error
        self.calls = 0

    def find_items(self, collection, bbox, asset_key="data", extra_query=None):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return list(self._items)


def _item(item_id="t1"):
    return PCItem(
        item_id=item_id,
        href=f"https://x/{item_id}.tif",
        asset_key="data",
        signed_href=f"https://x/{item_id}.tif?T",
    )


def _extent(xmin=30.0, ymin=50.0, xmax=31.0, ymax=51.0):
    return ExtentInfo(QgsRectangle(xmin, ymin, xmax, ymax), COMMON_CRS)


# ---------------------------------------------------------------- lat bounds
def test_srtm_outside_latitude_bounds(tmp_path):
    src = SRTMSource(str(tmp_path), pc_client=FakeClient(items=[_item()]))
    polar = _extent(ymin=70.0, ymax=75.0)

    assert src.is_available(polar) is False
    reason = src.unavailable_reason(polar)
    assert "60" in reason, "reason should mention the ±60° bounds"
    assert src.pc_client.calls == 0, "lat check must be offline (no STAC call)"


def test_srtm_inside_latitude_bounds_reaches_probe(tmp_path):
    src = SRTMSource(str(tmp_path), pc_client=FakeClient(items=[_item()]))
    assert src.is_available(_extent()) is True
    assert src.pc_client.calls == 1


def test_glo30_global_bounds_accept_high_latitude(tmp_path):
    src = GLO30Source(str(tmp_path), pc_client=FakeClient(items=[_item()]))
    assert src.is_available(_extent(ymin=70.0, ymax=75.0)) is True


# ---------------------------------------------------------------- STAC probe
def test_no_stac_items_means_unavailable(tmp_path):
    src = GLO30Source(str(tmp_path), pc_client=FakeClient(items=[]))
    assert src.is_available(_extent()) is False
    reason = src.unavailable_reason(_extent())
    assert "cop-dem-glo-30" in reason


def test_network_failure_assumes_available(tmp_path):
    src = GLO30Source(str(tmp_path), pc_client=FakeClient(error=PCError("boom")))
    assert src.is_available(_extent()) is True


def test_unconvertible_extent_is_unavailable(tmp_path):
    src = GLO30Source(str(tmp_path), pc_client=FakeClient(items=[_item()]))
    assert src.is_available(None) is False


# --------------------------------------------------------------- item cache
def test_items_cached_per_bbox(tmp_path):
    src = GLO30Source(str(tmp_path), pc_client=FakeClient(items=[_item()]))
    bbox = (30.0, 50.0, 31.0, 51.0)

    first = src.get_items_for_bbox(bbox)
    second = src.get_items_for_bbox(bbox)

    assert first == second
    assert src.pc_client.calls == 1, "identical bbox must reuse cached items"


# --------------------------------------------------------------- tile cache
def _stub_gdal_pipeline(monkeypatch, recorded):
    """Replace the heavy GDAL helpers with recorders."""

    def fake_build_vrt(paths):
        recorded["paths"] = list(paths)
        return "/tmp/fake.vrt"

    def fake_warp(**kwargs):
        recorded["warp"] = kwargs
        return kwargs["output_path"]

    def fake_cleanup(path):
        recorded["cleanup"] = path

    monkeypatch.setattr(base_mod, "build_vrt_for_items", fake_build_vrt)
    monkeypatch.setattr(base_mod, "warp_to_output", fake_warp)
    monkeypatch.setattr(base_mod, "cleanup_vrt", fake_cleanup)


def _fake_download_to_file(downloads):
    def _dl(url, dest, **kwargs):
        downloads.append((url, dest))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(b"fake tif bytes")
        return dest

    return _dl


def test_download_materialises_tiles_into_cache(tmp_path, monkeypatch):
    """download() must store PC tiles under cache_dir and VRT from local files."""
    src = GLO30Source(str(tmp_path), pc_client=FakeClient(items=[_item()]))
    downloads: list = []
    recorded: dict = {}

    monkeypatch.setattr(base_mod, "download_to_file", _fake_download_to_file(downloads))
    _stub_gdal_pipeline(monkeypatch, recorded)

    out = tmp_path / "out.tif"
    src.download(_extent(), str(out))

    assert len(downloads) == 1
    url, dest = downloads[0]
    assert url == "https://x/t1.tif?T", "tile must be fetched from the signed href"
    cached = os.path.join(src.cache_dir, "t1.tif")
    assert dest == cached and os.path.exists(cached)
    assert recorded["paths"] == [cached], "VRT must be built from the local tile"


def test_download_reuses_tiles_from_cache(tmp_path, monkeypatch):
    """A second run must hit the tile cache instead of re-downloading."""
    src = GLO30Source(str(tmp_path), pc_client=FakeClient(items=[_item()]))
    downloads: list = []
    recorded: dict = {}

    monkeypatch.setattr(base_mod, "download_to_file", _fake_download_to_file(downloads))
    _stub_gdal_pipeline(monkeypatch, recorded)

    out1 = tmp_path / "run1.tif"
    out2 = tmp_path / "run2.tif"
    src.download(_extent(), str(out1))
    src.download(_extent(), str(out2))

    assert len(downloads) == 1, "second run must read the tile from disk"
    cached = os.path.join(src.cache_dir, "t1.tif")
    assert recorded["paths"] == [cached]


def test_download_without_cache_streams_signed_hrefs(tmp_path, monkeypatch):
    """use_cache=False keeps the old streaming behaviour (no disk tiles)."""
    src = GLO30Source(str(tmp_path), pc_client=FakeClient(items=[_item()]), use_cache=False)
    downloads: list = []
    recorded: dict = {}

    monkeypatch.setattr(
        base_mod,
        "download_to_file",
        lambda *a, **k: downloads.append((a, k)) or pytest.fail("must not download"),
    )
    _stub_gdal_pipeline(monkeypatch, recorded)

    out = tmp_path / "out.tif"
    src.download(_extent(), str(out))

    assert downloads == [], "streaming mode must not fetch tiles to disk"
    assert recorded["paths"] == ["https://x/t1.tif?T"]


def test_download_cancelled_between_tiles(tmp_path, monkeypatch):
    """The is_cancelled hook must abort the tile loop before fetching."""
    from dem_comparator.core.orchestrator import OrchestratorCancelled

    src = GLO30Source(str(tmp_path), pc_client=FakeClient(items=[_item(), _item("t2")]))
    downloads: list = []
    recorded: dict = {}

    monkeypatch.setattr(base_mod, "download_to_file", _fake_download_to_file(downloads))
    _stub_gdal_pipeline(monkeypatch, recorded)

    out = tmp_path / "out.tif"
    with pytest.raises(OrchestratorCancelled):
        src.download(_extent(), str(out), is_cancelled=lambda: True)
    assert downloads == [], "cancelled run must not fetch any tile"


# ------------------------------------------------------------ vertical datum
def test_vertical_datums_declared():
    from dem_comparator.sources.aw3d30 import AW3D30Source
    from dem_comparator.sources.fabdem import FABDEMSource
    from dem_comparator.sources.nasadem import NASADEMSource

    assert FABDEMSource.vertical_datum == "EGM2008"
    assert GLO30Source.vertical_datum == "EGM2008"
    assert SRTMSource.vertical_datum == "EGM96"
    assert NASADEMSource.vertical_datum == "EGM96"
    assert AW3D30Source.vertical_datum == "EGM96"


def test_vertical_datum_mismatch_detected():
    fab = FABDEMLike()
    srtm = SRTMLike()
    assert base_mod.vertical_datum_mismatch([fab, srtm]) is not None
    assert base_mod.vertical_datum_mismatch([fab]) is None
    assert base_mod.vertical_datum_mismatch([]) is None
    warning = base_mod.vertical_datum_mismatch([fab, srtm])
    assert "EGM96" in warning and "EGM2008" in warning


def test_vertical_datum_summary_groups_by_datum():
    fab = FABDEMLike()
    srtm = SRTMLike()
    summary = base_mod.vertical_datum_summary([fab, srtm])
    assert "EGM2008 (FABDEM)" in summary
    assert "EGM96 (SRTM)" in summary


class FABDEMLike:
    name = "FABDEM"
    vertical_datum = "EGM2008"


class SRTMLike:
    name = "SRTM"
    vertical_datum = "EGM96"
