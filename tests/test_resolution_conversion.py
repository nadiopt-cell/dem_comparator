"""Tests for latitude-aware metre→degree resolution conversion (issue #1).

Pure logic — runs anywhere (uses the qgis/osgeo stubs from conftest).
Acceptance from the issue: at mid-latitudes the grid step must correspond
to the requested metres on the ground within ~1%, instead of being computed
with the equator factor for both axes.
"""
from __future__ import annotations

import math

from conftest import HAVE_QGIS  # noqa: F401  (ensures stubs load first)

from dem_comparator.core.align import (  # noqa: E402
    Aligner,
    make_aligner,
    metres_per_degree_latitude,
    metres_per_degree_longitude,
)

# ------------------------------------------------------- geodesic helpers


def test_metres_per_degree_latitude_equator():
    # Series: 111132.92 - 559.82·cos0 + 1.175·cos0 - 0.0023·cos0
    expected = 111_132.92 - 559.82 + 1.175 - 0.0023
    assert math.isclose(metres_per_degree_latitude(0.0), expected, rel_tol=1e-9)
    # WGS84 equatorial meridian arc ≈ 110 574 m/deg.
    assert abs(metres_per_degree_latitude(0.0) - 110_574.3) < 5.0


def test_metres_per_degree_latitude_60n():
    # At 60°: 111132.92 + 559.82·0.5 - 1.175·0.5 - 0.0023 ≈ 111 412 m/deg.
    assert abs(metres_per_degree_latitude(60.0) - 111_412.2) < 5.0


def test_metres_per_degree_longitude_equator_and_60n():
    # Equator: 111412.84 - 93.5 + 0.118 ≈ 111 319.5 m/deg (WGS84 ≈ 111 319.5).
    assert abs(metres_per_degree_longitude(0.0) - 111_319.5) < 5.0
    # 60°: 111412.84·0.5 + 93.5 + 0.118·0.5 ≈ 55 800 m/deg (half of equator;
    # the series terms cos(3φ)/cos(5φ) shift it ~0.25% off the exact half).
    val = metres_per_degree_longitude(60.0)
    assert abs(val - 55_800.0) < 5.0
    assert math.isclose(val, metres_per_degree_longitude(0.0) / 2, rel_tol=5e-3)


# ------------------------------------------------------------- make_aligner


def test_make_aligner_latitude_aware_ground_size_within_1pct():
    """Acceptance: at 60° N the ground sampling must equal 30 m ±1%.

    The legacy equator-only conversion would produce ~55.8 m east-west at
    60° N — this test fails for the old behaviour by construction.
    """
    centre_lat = 60.0
    aligner = make_aligner("/tmp", resolution_m=30.0, centre_lat_deg=centre_lat)

    ground_x = aligner.resolution_deg * metres_per_degree_longitude(centre_lat)
    ground_y = aligner.resolution_deg_y * metres_per_degree_latitude(centre_lat)
    assert math.isclose(ground_x, 30.0, rel_tol=0.01)
    assert math.isclose(ground_y, 30.0, rel_tol=0.01)

    # X step must be about twice the Y step at 60° N (cos(60°) = 0.5).
    ratio = aligner.resolution_deg / aligner.resolution_deg_y
    assert 1.9 < ratio < 2.1


def test_make_aligner_legacy_mode_unchanged():
    """centre_lat_deg=None keeps the historical equator-only behaviour."""
    aligner = make_aligner("/tmp", resolution_m=30.0, centre_lat_deg=None)
    expected_deg = 30.0 / 111_320.0
    assert math.isclose(aligner.resolution_deg, expected_deg, rel_tol=1e-9)
    assert math.isclose(aligner.resolution_deg_y, expected_deg, rel_tol=1e-9)


def test_make_aligner_default_is_latitude_aware():
    """No latitude given → still equator-only (backward-compatible default)."""
    aligner = make_aligner("/tmp", resolution_m=30.0)
    assert math.isclose(aligner.resolution_deg, 30.0 / 111_320.0, rel_tol=1e-9)


def test_make_aligner_clamps_extreme_polar_latitudes():
    """|lat| > 82° must be clamped so the X step cannot explode."""
    a = make_aligner("/tmp", resolution_m=30.0, centre_lat_deg=89.5)
    b = make_aligner("/tmp", resolution_m=30.0, centre_lat_deg=82.0)
    assert math.isclose(a.resolution_deg, b.resolution_deg, rel_tol=1e-9)
    # And the clamped value stays sane (~30 m / 15.5 km per degree ≈ 1.9e-3°).
    assert a.resolution_deg < 0.01


def test_aligner_rejects_invalid_y_resolution(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        Aligner(str(tmp_path), resolution_deg=0.01, resolution_deg_y=0.0)
    with pytest.raises(ValueError):
        Aligner(str(tmp_path), resolution_deg=0.01, resolution_deg_y=-0.5)
