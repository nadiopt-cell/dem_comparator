"""FABDEM (Forest And Buildings removed DEM) — via Microsoft Planetary Computer."""
from __future__ import annotations

from qgis.core import QgsProcessingFeedback, QgsRectangle
from qgis.core import QgsCoordinateReferenceSystem

from .base import BaseDEMSource, PCTileSpec


class FABDEMSource(BaseDEMSource):
    id = "fabdem"
    name = "FABDEM (30 m, DTM)"
    dem_type = "DTM"
    pc_spec = PCTileSpec(collection="fabdem", asset_key="data", native_resolution_m=30.0)
    description = (
        "Forest And Buildings DEM — Copernicus GLO-30 with forests and buildings "
        "removed. Mirrored on Microsoft Planetary Computer."
    )

    # Coverage is global (same as Copernicus DEM).
    def is_available(self, extent, crs: QgsCoordinateReferenceSystem | None = None) -> bool:
        return True


Source = FABDEMSource