"""Abstract base class for every DEM source.

A source is responsible for:

1. Telling the UI about itself (id, name, type, native resolution).
2. Saying whether it can serve a given extent (with a clear, user-readable
   reason if not).
3. Producing a single GeoTIFF on disk that covers the requested extent.

Availability is checked in two stages:

* **Fast offline check** — latitude bounds declared per source (SRTM is
  only between 60°S–60°N, etc.). No network needed.
* **Honest online check** — a lightweight STAC ``search`` (limit=1) on
  Microsoft Planetary Computer. If the catalogue returns no items for
  the bbox, the source genuinely cannot serve the extent (ocean-only
  bbox outside tile coverage, polar gap, …). Results are cached per
  bbox and reused by :meth:`download`, so the same search is never paid
  for twice.

If the online check itself fails (network down, PC unreachable) we do
NOT mark the source unavailable — we assume available and let the
download phase surface the real error.

In this MVP, every source inherits the same download skeleton — a STAC
search through :class:`PlanetaryComputerClient` followed by a mosaic + clip
through :mod:`core.pc_mosaic`. Subclasses only have to declare the PC
``collection`` id, the right ``asset_key`` for that collection and
(optional) latitude bounds.
"""
from __future__ import annotations

import os
from abc import ABC
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsProcessingFeedback,
)

from ..core.pc_client import PCError, PlanetaryComputerClient, PCItem
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

    # Latitude coverage bounds in EPSG:4326 degrees. Subclasses narrow
    # these (SRTM/NASADEM: ±60°, AW3D30: ±82°); "global" sources keep the
    # defaults. The bounds are the fast, offline part of is_available().
    lat_min: float = -90.0
    lat_max: float = 90.0

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
        # STAC results cache, keyed by a rounded WGS84 bbox tuple so that
        # is_available() can warm it and download() reuses it.
        self._items_cache: Dict[Tuple[float, float, float, float], List[PCItem]] = {}

    # ---------------------------------------------------- public metadata
    @property
    def native_resolution_m(self) -> float:
        return self.pc_spec.native_resolution_m

    # ----------------------------------------------------------- capability
    @staticmethod
    def _bbox_cache_key(bbox: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
        """Round a WGS84 bbox to ~1 km so near-identical bboxes share cache."""
        return tuple(round(float(v), 4) for v in bbox)  # type: ignore[return-value]

    def _bbox_for(self, extent) -> Tuple[float, float, float, float]:
        """Convert ``extent`` (ExtentInfo-like) to a WGS84 bbox tuple."""
        from ..core.extent_utils import to_common_grid

        common = to_common_grid(extent)
        return (
            common.rectangle.xMinimum(),
            common.rectangle.yMinimum(),
            common.rectangle.xMaximum(),
            common.rectangle.yMaximum(),
        )

    def _lat_problem(self, bbox: Tuple[float, float, float, float]) -> Optional[str]:
        """Return a reason string if the bbox violates latitude bounds."""
        ymin, ymax = bbox[1], bbox[3]
        if ymax < self.lat_min or ymin > self.lat_max:
            return (
                f"{self.name} covers latitudes {self.lat_min:g}° … {self.lat_max:g}°; "
                f"the requested extent ({ymin:.2f}° … {ymax:.2f}°) is outside it."
            )
        return None

    def is_available(
        self,
        extent,
        crs: Optional[QgsCoordinateReferenceSystem] = None,
    ) -> bool:
        """Return True if this source can plausibly serve ``extent``.

        Two-stage check (see module docstring): fast latitude bounds,
        then a cached STAC probe. Network failures during the probe are
        not treated as "unavailable" — the download phase will report
        the real error if there is one.
        """
        try:
            bbox = self._bbox_for(extent)
        except Exception:
            return False

        if self._lat_problem(bbox) is not None:
            return False

        try:
            items = self.get_items_for_bbox(bbox)
        except PCError:
            # Cannot verify right now — assume available and let the
            # download phase produce a precise error message.
            return True
        return len(items) > 0

    def unavailable_reason(self, extent) -> str:
        """User-readable reason why :meth:`is_available` returned False."""
        try:
            bbox = self._bbox_for(extent)
        except Exception as exc:
            return f"Extent cannot be converted to WGS84: {exc}"

        lat_problem = self._lat_problem(bbox)
        if lat_problem is not None:
            return lat_problem
        return (
            f"Planetary Computer returned no '{self.pc_spec.collection}' items "
            f"for the requested extent — it may be outside the dataset coverage."
        )

    # ---------------------------------------------------------------- items
    def get_items_for_bbox(
        self,
        bbox: Tuple[float, float, float, float],
        feedback: Optional[QgsProcessingFeedback] = None,
    ) -> List[PCItem]:
        """Return STAC items for ``bbox`` (WGS84), cached per rounded bbox."""
        key = self._bbox_cache_key(bbox)
        cached = self._items_cache.get(key)
        if cached is not None:
            return cached

        spec = self.pc_spec
        if feedback is not None:
            feedback.pushInfo(f"[{self.id}] STAC search for collection '{spec.collection}'")
        items = self.pc_client.find_items(
            collection=spec.collection,
            bbox=bbox,
            asset_key=spec.asset_key,
        )
        self._items_cache[key] = items
        return items

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
        items = self.get_items_for_bbox(bbox, feedback=feedback)
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