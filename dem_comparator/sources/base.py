"""Abstract base class for every DEM source.

A source is responsible for:

1. Telling the UI about itself (id, name, type, native resolution).
2. Saying whether it can serve a given extent (with a clear, user-readable
   reason if not).
3. Producing a single GeoTIFF on disk that covers the requested extent.

In this MVP, every source inherits the same download skeleton — a STAC
search through :class:`PlanetaryComputerClient` followed by a mosaic + clip
through :mod:`core.pc_mosaic`. Subclasses only have to declare the PC
``collection`` id and the right ``asset_key`` for that collection.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsProcessingFeedback,
    QgsRectangle,
)

from ..core.pc_client import PlanetaryComputerClient
from ..core.pc_mosaic import build_vrt_for_items, cleanup_vrt, warp_to_output


@dataclass(frozen=True)
class PCTileSpec:
    """Per-source PC-specific configuration."""

    collection: str        # STAC collection id on Planetary Computer
    asset_key: str         # asset key inside each item ("data" / "elevation")
    native_resolution_m: float = 30.0


class BaseDEMSource(ABC):
    """Abstract base class for a DEM source."""

    id: str = ""
    name: str = ""
    dem_type: str = "DSM"     # "DSM" or "DTM"
    description: str = ""

    # Concrete subclasses declare their PC configuration via ``pc_spec``.
    # (We keep it on the class — not the instance — so that the registry
    # can list providers without instantiating them.)
    pc_spec: PCTileSpec = PCTileSpec(collection="", asset_key="data")

    def __init__(
        self,
        cache_dir: str,
        pc_client: Optional[PlanetaryComputerClient] = None,
    ) -> None:
        self.cache_dir = os.path.join(cache_dir, self.id)
        self.pc_client = pc_client or PlanetaryComputerClient()

    # ---------------------------------------------------- public metadata
    @property
    def native_resolution_m(self) -> float:
        return self.pc_spec.native_resolution_m

    # ----------------------------------------------------------- capability
    def is_available(
        self,
        extent,
        crs: Optional[QgsCoordinateReferenceSystem] = None,
    ) -> bool:
        """Return True if this source can serve ``extent``."""
        try:
            from ..core.extent_utils import to_common_grid

            to_common_grid(extent)
        except Exception:
            return False
        return True

    def unavailable_reason(self, extent) -> str:
        return "Selected extent is outside this source's coverage."

    # ---------------------------------------------------------------- fetch
    def download(
        self,
        extent,
        output_path: str,
        feedback: Optional[QgsProcessingFeedback] = None,
        is_cancelled=None,
    ) -> str:
        """Default download pipeline: PC STAC search + VRT mosaic + GDAL Warp."""
        from ..core.extent_utils import to_common_grid

        common = to_common_grid(extent)
        bbox = (
            common.rectangle.xMinimum(),
            common.rectangle.yMinimum(),
            common.rectangle.xMaximum(),
            common.rectangle.yMaximum(),
        )

        spec = self.pc_spec
        if feedback is not None:
            feedback.pushInfo(f"[{self.id}] STAC search for collection '{spec.collection}'")

        items = self.pc_client.find_items(
            collection=spec.collection,
            bbox=bbox,
            asset_key=spec.asset_key,
        )
        if not items:
            raise RuntimeError(
                f"Planetary Computer returned no items for {self.name} "
                f"in bbox {bbox}. The area may be outside the dataset coverage."
            )

        if feedback is not None:
            feedback.pushInfo(f"[{self.id}] {len(items)} item(s); building mosaic VRT")
        vrt_path = build_vrt_for_items(item.signed_href for item in items)

        try:
            # 30 m at the equator ≈ 30 / 111320 degrees.
            resolution_deg = spec.native_resolution_m / 111_320.0
            warp_to_output(
                vrt_path=vrt_path,
                output_path=output_path,
                bbox_wgs84=bbox,
                resolution_deg=resolution_deg,
                resampling="bilinear",
            )
        finally:
            cleanup_vrt(vrt_path)

        if feedback is not None:
            feedback.pushInfo(f"[{self.id}] saved -> {output_path}")
        return output_path

    # ---------------------------------------------------------- convenience
    @property
    def cache_root(self) -> str:
        return self.cache_dir

    @staticmethod
    def output_dir_for(source_id: str, base_dir: str) -> str:
        path = os.path.join(base_dir, source_id)
        os.makedirs(path, exist_ok=True)
        return path


def default_source_cache_dir(profile_cache_root: str) -> str:
    """Return the root directory used by all DEM sources."""
    return os.path.join(profile_cache_root, "dem_comparator_cache")


__all__ = ["BaseDEMSource", "PCTileSpec", "default_source_cache_dir"]