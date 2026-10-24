"""ALOS World 3D-30 (JAXA) — via Microsoft Planetary Computer."""
from __future__ import annotations

from .base import BaseDEMSource, PCTileSpec


class AW3D30Source(BaseDEMSource):
    id = "aw3d30"
    name = "ALOS World 3D-30 (30 m, DSM)"
    dem_type = "DSM"
    pc_spec = PCTileSpec(collection="alos-dem", asset_key="data", native_resolution_m=30.0)
    description = (
        "ALOS World 3D-30 (JAXA). Mirrored on Microsoft Planetary Computer. "
        "License: free for non-military use."
    )

    # AW3D30 global release covers 82°S … 82°N.
    lat_min = -82.0
    lat_max = 82.0


Source = AW3D30Source
