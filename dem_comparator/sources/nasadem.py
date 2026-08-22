"""NASADEM (NASA JPL reprocessing of SRTM) — via Microsoft Planetary Computer."""
from __future__ import annotations

from .base import BaseDEMSource, PCTileSpec


class NASADEMSource(BaseDEMSource):
    id = "nasadem"
    name = "NASADEM (30 m, DSM)"
    dem_type = "DSM"
    pc_spec = PCTileSpec(collection="nasadem", asset_key="elevation", native_resolution_m=30.0)
    description = (
        "NASADEM — NASA JPL reprocessed SRTM with improved noise removal. "
        "Mirrored on Microsoft Planetary Computer (asset key 'elevation')."
    )

    LAT_MIN = -60.0
    LAT_MAX = 60.0

    def is_available(self, extent, crs=None) -> bool:
        from qgis.core import QgsCoordinateReferenceSystem

        if extent.crs.authid() != "EPSG:4326":
            return False
        y0, y1 = extent.rectangle.yMinimum(), extent.rectangle.yMaximum()
        return not (y1 < self.LAT_MIN or y0 > self.LAT_MAX)

    def unavailable_reason(self, extent) -> str:
        return "NASADEM coverage is between 60°S and 60°N latitude."


Source = NASADEMSource