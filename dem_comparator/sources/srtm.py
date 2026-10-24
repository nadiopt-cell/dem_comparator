"""SRTM v3 (NASA / USGS, 1 arc-second) — via Microsoft Planetary Computer."""
from __future__ import annotations

from .base import BaseDEMSource, PCTileSpec


class SRTMSource(BaseDEMSource):
    id = "srtm"
    name = "SRTM v3 (1 arc-sec, 30 m)"
    dem_type = "DSM"
    pc_spec = PCTileSpec(collection="srtm-gl-1", asset_key="elevation", native_resolution_m=30.0)
    description = (
        "Shuttle Radar Topography Mission reprocessed by NASA/USGS. "
        "Mirrored on Microsoft Planetary Computer (asset key 'elevation')."
    )

    # Classic SRTM coverage: 60°S … 60°N.
    lat_min = -60.0
    lat_max = 60.0


Source = SRTMSource
