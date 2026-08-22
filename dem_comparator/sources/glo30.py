"""Copernicus GLO-30 (ESA) — via Microsoft Planetary Computer."""
from __future__ import annotations

from .base import BaseDEMSource, PCTileSpec


class GLO30Source(BaseDEMSource):
    id = "glo30"
    name = "Copernicus GLO-30 (30 m, DSM)"
    dem_type = "DSM"
    pc_spec = PCTileSpec(collection="cop-dem-glo-30", asset_key="data", native_resolution_m=30.0)
    description = (
        "ESA Copernicus DEM GLO-30 — global 30 m DSM. "
        "Mirrored on Microsoft Planetary Computer."
    )

    def is_available(self, extent, crs=None) -> bool:
        return True


Source = GLO30Source