"""Tests for the Planetary Computer client (pure stdlib — run anywhere).

Covers SAS-token caching, signed-href idempotency, STAC pagination,
asset fallback selection and filename sanitisation.
"""
from __future__ import annotations

import pytest

from conftest import HAVE_QGIS  # noqa: F401  (ensures stubs load first)

from dem_comparator.core.pc_client import (
    PCError,
    PCItem,
    PlanetaryComputerClient,
    _safe_filename,
)


@pytest.fixture
def client():
    return PlanetaryComputerClient(token_cache_path=None)


# --------------------------------------------------------------------- token
def test_sas_token_is_cached(client, monkeypatch):
    calls = {"n": 0}

    def fake_get(url):
        calls["n"] += 1
        return {"token": "tok-1"}

    monkeypatch.setattr(client, "_http_get_json", fake_get)

    t1 = client.get_sas_token("srtm-gl-1")
    t2 = client.get_sas_token("srtm-gl-1")

    assert t1 == t2 == "tok-1"
    assert calls["n"] == 1, "second call must hit the in-memory cache"


def test_sas_token_error_raised(client, monkeypatch):
    monkeypatch.setattr(client, "_http_get_json", lambda url: {"unexpected": 1})
    with pytest.raises(PCError):
        client.get_sas_token("srtm-gl-1")


# ----------------------------------------------------------------- sign href
def test_sign_href_appends_token():
    out = PlanetaryComputerClient.sign_href("https://x/blob.tif", "T")
    assert out == "https://x/blob.tif?T"


def test_sign_href_is_idempotent():
    once = PlanetaryComputerClient.sign_href("https://x/blob.tif", "T")
    twice = PlanetaryComputerClient.sign_href(once, "T")
    assert once == twice


def test_sign_href_uses_ampersand_when_query_present():
    out = PlanetaryComputerClient.sign_href("https://x/blob.tif?a=1", "T")
    assert out == "https://x/blob.tif?a=1&T"


# ------------------------------------------------------------------ search
def test_search_follows_pagination(client, monkeypatch):
    page1 = {
        "features": [{"id": "a", "assets": {}}],
        "links": [{"rel": "next", "href": "https://pc/next"}],
    }
    page2 = {"features": [{"id": "b", "assets": {}}], "links": []}

    monkeypatch.setattr(client, "_http_post_json", lambda url, body: page1)
    monkeypatch.setattr(client, "_http_get_json", lambda url: page2)

    items = client.search_items("srtm-gl-1", (0.0, 0.0, 1.0, 1.0))
    assert [i["id"] for i in items] == ["a", "b"]


def test_next_link_extraction():
    payload = {"links": [{"rel": "self", "href": "x"}, {"rel": "next", "href": "y"}]}
    assert PlanetaryComputerClient._next_link(payload) == "y"
    assert PlanetaryComputerClient._next_link({"links": []}) is None


# --------------------------------------------------------------- find items
def test_find_items_prefers_named_asset(client, monkeypatch):
    raw = {
        "features": [
            {
                "id": "item1",
                "assets": {
                    "thumbnail": {"href": "https://x/t.png", "type": "image/png"},
                    "data": {"href": "https://x/dem.tif", "type": "image/tiff"},
                },
            }
        ]
    }
    monkeypatch.setattr(client, "get_sas_token", lambda c: "T")
    monkeypatch.setattr(client, "search_items", lambda *a, **k: raw["features"])

    items = client.find_items("srtm-gl-1", (0, 0, 1, 1), asset_key="data")
    assert len(items) == 1
    assert items[0].asset_key == "data"
    assert items[0].signed_href == "https://x/dem.tif?T"


def test_find_items_falls_back_to_raster_asset(client, monkeypatch):
    raw = {
        "features": [
            {
                "id": "item2",
                "assets": {
                    "elevation": {"href": "https://x/elev.tif", "type": "image/tiff"},
                },
            }
        ]
    }
    monkeypatch.setattr(client, "get_sas_token", lambda c: "T")
    monkeypatch.setattr(client, "search_items", lambda *a, **k: raw["features"])

    items = client.find_items("nasadem", (0, 0, 1, 1), asset_key="missing")
    assert len(items) == 1
    assert items[0].asset_key == "elevation"


# ------------------------------------------------------------ misc helpers
def test_safe_filename():
    assert _safe_filename("https://pc/Some Path/Weird~Name.tif?token=1") == "Weird_Name.tif"
    assert _safe_filename("https://pc/noext") == "noext.tif"
