"""Tests for BaseDEMSource availability logic and the STAC item cache.

These tests run anywhere: with real QGIS bindings or with the stubs from
conftest (the availability logic itself is pure Python + one client call).
"""
from __future__ import annotations

import pytest

from conftest import HAVE_QGIS  # noqa: F401  (ensures stubs load first)

from dem_comparator.core.extent_utils import COMMON_CRS, ExtentInfo, QgsRectangle
from dem_comparator.core.pc_client import PCError, PCItem
from dem_comparator.sources.srtm import SRTMSource
from dem_comparator.sources.glo30 import GLO30Source


class FakeClient:
    """PlanetaryComputerClient double with a scriptable find_items."""

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


def test_download_reuses_items_from_cache(tmp_path, monkeypatch):
    """download() must not re-run find_items when is_available() warmed it."""
    src = GLO30Source(str(tmp_path), pc_client=FakeClient(items=[_item()]))
    extent = _extent()

    # Warm the cache the way the orchestrator does before downloading.
    assert src.is_available(extent) is True
    assert src.pc_client.calls == 1

    # Replace the heavy GDAL helpers with recorders.
    recorded = {}

    def fake_build_vrt(hrefs):
        recorded["hrefs"] = list(hrefs)
        return "/tmp/fake.vrt"

    def fake_warp(**kwargs):
        recorded["warp"] = kwargs
        return kwargs["output_path"]

    def fake_cleanup(path):
        recorded["cleanup"] = path

    from dem_comparator.sources import base as base_mod

    monkeypatch.setattr(base_mod, "build_vrt_for_items", fake_build_vrt)
    monkeypatch.setattr(base_mod, "warp_to_output", fake_warp)
    monkeypatch.setattr(base_mod, "cleanup_vrt", fake_cleanup)

    out = tmp_path / "out.tif"
    src.download(extent, str(out))

    assert src.pc_client.calls == 1, "download must reuse the cached STAC search"
    assert recorded["hrefs"] == ["https://x/t1.tif?T"]
    assert recorded["warp"]["output_path"] == str(out)
