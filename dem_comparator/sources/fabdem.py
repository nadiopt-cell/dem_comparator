"""FABDEM (Forest And Buildings removed DEM) — via Microsoft Planetary Computer."""
from __future__ import annotations

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

    vertical_datum = "EGM2008"

    # Coverage follows Copernicus GLO-30 (global); FABDEM tiles only exist
    # over land — the STAC probe in BaseDEMSource.is_available() filters
    # ocean-only bboxes honestly at run time.


Source = FABDEMSource
