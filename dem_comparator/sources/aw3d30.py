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

    LAT_MIN = -82.0
    LAT_MAX = 82.0

    def is_available(self, extent, crs=None) -> bool:
        from qgis.core import QgsCoordinateReferenceSystem

        if extent.crs.authid() != "EPSG:4326":
            return False
        y0, y1 = extent.rectangle.yMinimum(), extent.rectangle.yMaximum()
        return not (y1 < self.LAT_MIN or y0 > self.LAT_MAX)

    def unavailable_reason(self, extent) -> str:
        return "AW3D30 coverage is between 82°S and 82°N latitude."


Source = AW3D30Source