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

    # NASADEM inherits the SRTM footprint: 60°S … 60°N.
    vertical_datum = "EGM96"
    lat_min = -60.0
    lat_max = 60.0


Source = NASADEMSource
