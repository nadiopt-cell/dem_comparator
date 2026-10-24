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
import re
from abc import ABC
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsProcessingFeedback,
)

from ..core.pc_client import (
    PCError,
    PCItem,
    PlanetaryComputerClient,
    download_to_file,
)
from ..core.pc_mosaic import build_vrt_for_items, cleanup_vrt, warp_to_output

_SAFE_ITEM_ID = re.compile(r"[^A-Za-z0-9._-]+")


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

    # Vertical datum of the published heights (issue #6). The three
    # radar/photogrammetric surface models are referenced to the EGM96
    # geoid, while the Copernicus family (GLO-30 and FABDEM, which is
    # derived from it) uses EGM2008. Mixing the two families shifts
    # heights by the local geoid difference (usually decimetres, up to a
    # few metres regionally) — the orchestrator turns a mixed selection
    # into a warning plus a report note.
    vertical_datum: str = ""

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
        use_cache: bool = True,
    ) -> None:
        self.cache_dir = os.path.join(cache_dir, self.id)
        self.pc_client = pc_client or PlanetaryComputerClient()
        # Tile cache (issue #5): when enabled, PC COG tiles are materialised
        # under ``cache_dir`` once and reused by later runs. Disable to
        # stream tiles straight from PC (old behaviour, no disk usage).
        self.use_cache = use_cache
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
    def _tile_cache_path(self, item: PCItem) -> str:
        """On-disk cache path for one STAC item's COG."""
        safe_id = _SAFE_ITEM_ID.sub("_", item.item_id) or "tile"
        return os.path.join(self.cache_dir, f"{safe_id}.tif")

    def _ensure_local_tile(
        self,
        item: PCItem,
        feedback: Optional[QgsProcessingFeedback] = None,
    ) -> str:
        """Return a GDAL-openable path for ``item``'s raster.

        With ``use_cache`` on, the tile is downloaded once into
        ``cache_dir`` and later runs hit the disk (issue #5) — this also
        makes long warps immune to SAS-token expiry, because the token is
        only baked into the URL during the initial fetch. With
        ``use_cache`` off, the signed href is returned and GDAL streams
        the tile over ``/vsicurl/`` (previous behaviour).
        """
        if not self.use_cache:
            return item.signed_href

        path = self._tile_cache_path(item)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            if feedback is not None:
                feedback.pushInfo(f"[{self.id}] tile cache hit: {os.path.basename(path)}")
            return path

        os.makedirs(self.cache_dir, exist_ok=True)
        if feedback is not None:
            feedback.pushInfo(f"[{self.id}] fetching tile {item.item_id} into cache")
        download_to_file(
            item.signed_href,
            path,
            user_agent=self.pc_client.user_agent,
            feedback=feedback,
        )
        return path

    def download(
        self,
        extent,
        output_path: str,
        feedback: Optional[QgsProcessingFeedback] = None,
        is_cancelled=None,
    ) -> str:
        """Default download pipeline: PC STAC search + local tile cache +
        VRT mosaic + GDAL Warp.

        :param is_cancelled: optional ``callable() -> bool`` checked before
            every tile fetch so cancelling stops promptly mid-download.
        """
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
            feedback.pushInfo(f"[{self.id}] {len(items)} item(s)")

        local_tiles: List[str] = []
        for item in items:
            if is_cancelled is not None and is_cancelled():
                from ..core.orchestrator import OrchestratorCancelled

                raise OrchestratorCancelled(
                    "Run cancelled by user during tile download."
                )
            local_tiles.append(self._ensure_local_tile(item, feedback=feedback))

        if feedback is not None:
            feedback.pushInfo(f"[{self.id}] building mosaic VRT")
        vrt_path = build_vrt_for_items(local_tiles)

        try:
            # Native resolution converted to degrees at the equator; the
            # final latitude-aware gridding happens later in the Aligner.
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


# ------------------------------------------------------------- vertical datum

def vertical_datum_summary(sources: Sequence[BaseDEMSource]) -> str:
    """One-line summary of the vertical datums of ``sources`` (report param)."""
    groups: Dict[str, List[str]] = {}
    for src in sources:
        datum = src.vertical_datum or "unspecified"
        groups.setdefault(datum, []).append(src.name)
    return "; ".join(
        f"{datum} ({', '.join(names)})" for datum, names in groups.items()
    )


def vertical_datum_mismatch(sources: Sequence[BaseDEMSource]) -> Optional[str]:
    """Return a warning string when selected sources mix vertical datums.

    ``None`` when the selection is consistent (single datum, or sources
    that do not declare one).
    """
    datums = {
        src.vertical_datum for src in sources if src.vertical_datum
    }
    if len(datums) <= 1:
        return None
    return (
        "Mixed vertical datums in this run: "
        + vertical_datum_summary(sources)
        + ". Heights differ by the local EGM96/EGM2008 geoid separation "
        "(usually decimetres, up to a few metres regionally); treat the "
        "mean bias between such pairs accordingly or convert to a common "
        "datum first."
    )


__all__ = [
    "BaseDEMSource",
    "PCTileSpec",
    "default_source_cache_dir",
    "vertical_datum_mismatch",
    "vertical_datum_summary",
]