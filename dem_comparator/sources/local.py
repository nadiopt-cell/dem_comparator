"""Local DEM files (GeoTIFF and friends) as comparison inputs — issue #4.

The typical real-world scenario: compare a *local* high-resolution DEM
(lidar DTM, UAV photogrammetry, national DTM) against the global sources
the plugin downloads (GLO-30, FABDEM, …). Local files are treated as
pseudo-sources: they enter the pipeline at the very same point as the
downloaded ones (alignment stage) and are clipped to the selected extent
and reprojected to EPSG:4326 exactly like the downloaded rasters, so the
rest of the pipeline (Aligner → Comparator → report) needs no changes.

Design notes:

* Instances are built from absolute file paths. ``id`` must be unique
  within one run (two files may share a basename), so use
  :func:`assign_local_ids` — a pure function shared by the dialog (for
  the reference combo) and the plugin (for source construction) —
  guaranteeing both sides derive identical ids.
* The vertical datum of a local file is unknown → ``vertical_datum``
  stays empty and the report shows "unspecified".
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

from qgis.core import QgsProcessingFeedback

from ..core.extent_utils import COMMON_CRS
from .base import BaseDEMSource

_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]+")

# Files that GDAL can open but that are not real DEMs would only blow up
# at the alignment stage with a cryptic error; warn about typical
# mistakes right in the dialog instead (cheap extension check).
_COMMON_DEM_EXTENSIONS = (".tif", ".tiff", ".gtiff", ".img", ".asc", ".grd")


def _base_id(path: str) -> str:
    """Filesystem-safe base id for a local file (basename w/o extension)."""
    stem = os.path.splitext(os.path.basename(path))[0]
    safe = _SAFE_ID.sub("_", stem).strip("_")
    return safe or "local_dem"


def assign_local_ids(paths: List[str]) -> Dict[str, str]:
    """Map ``path → unique source id`` for a batch of local files.

    Pure function (no filesystem access beyond the paths given) so the
    dialog and the plugin always agree on the ids of a run.
    """
    taken: Dict[str, str] = {}
    counts: Dict[str, int] = {}
    for path in paths:
        base = _base_id(path)
        counts[base] = counts.get(base, 0) + 1
        sid = base if counts[base] == 1 else f"{base}_{counts[base]}"
        taken[path] = sid
    return taken


class LocalDEMSource(BaseDEMSource):
    """A DEM read from a user-provided raster file."""

    dem_type = "unknown"      # a lidar DTM? a UAV DSM? — unknown
    vertical_datum = ""       # unknown → "unspecified" in the report
    description = "User-provided local raster"

    def __init__(
        self,
        path: str,
        source_id: str,
        cache_dir: str,
        pc_client=None,
        use_cache: bool = True,
    ) -> None:
        # ``id`` must be set *before* super().__init__(): the base class
        # derives the per-source cache subdirectory from it.
        self.id = source_id
        self.path = os.path.abspath(path)
        self.name = os.path.basename(self.path)
        super().__init__(cache_dir, pc_client=pc_client, use_cache=use_cache)

    # ----------------------------------------------------------- capability
    def is_available(self, extent, crs=None) -> bool:
        """A local source is available when its file exists (and is readable).

        The overlap with the requested extent is *not* checked here —
        GDAL cannot be assumed cheap at this point (it would open the
        file); a file that does not intersect the AOI fails loudly at
        the download stage with a clear error message.
        """
        return os.path.isfile(self.path)

    def unavailable_reason(self, extent) -> str:
        if not os.path.isfile(self.path):
            return f"Local DEM file not found: {self.path}"
        return f"Local DEM file cannot be used: {self.path}"

    # ---------------------------------------------------------------- fetch
    def download(
        self,
        extent,
        output_path: str,
        feedback: Optional[QgsProcessingFeedback] = None,
        is_cancelled=None,
    ) -> str:
        """Clip + reproject the local file to the common grid footprint.

        The orchestrator's alignment stage assumes every "raw" raster is
        already in EPSG:4326 (its grid math works in degrees), so this
        step always runs — even for files that already are in EPSG:4326,
        because it also clips them to the selected extent.
        """
        if is_cancelled is not None and is_cancelled():
            from ..core.orchestrator import OrchestratorCancelled

            raise OrchestratorCancelled("Run cancelled by user before processing.")

        from osgeo import gdal

        gdal.UseExceptions()

        ds = gdal.Open(self.path, gdal.GA_ReadOnly)
        if ds is None:
            raise RuntimeError(f"Cannot open local DEM: {self.path}")
        band = ds.GetRasterBand(1)
        src_nodata = band.GetNoDataValue()
        bbox = self._bbox_for(extent)
        ds = None  # close: Warp opens the file itself

        if feedback is not None:
            feedback.pushInfo(
                f"[{self.id}] clipping/reprojecting {self.name} -> EPSG:4326"
            )

        warp_kwargs = dict(
            format="GTiff",
            dstSRS=COMMON_CRS.authid(),
            outputBounds=list(bbox),
            dstNodata=-9999.0,
            creationOptions=["COMPRESS=DEFLATE", "TILED=YES"],
        )
        if src_nodata is not None:
            warp_kwargs["srcNodata"] = src_nodata

        try:
            gdal.Warp(output_path, self.path, **warp_kwargs)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to clip/reproject {self.name}: {exc}. "
                f"Check that the file intersects the selected extent."
            ) from exc

        # Detect the "file does not intersect the AOI" case: GDAL happily
        # writes an all-nodata raster instead of failing.
        chk = gdal.Open(output_path, gdal.GA_ReadOnly)
        try:
            stats = chk.GetRasterBand(1).GetStatistics(approx_ok=True, force=True)
            if not stats or stats[1] <= stats[0]:  # min >= max → no data at all
                os.remove(output_path)
                raise RuntimeError(
                    f"{self.name}: no valid pixels inside the selected extent "
                    f"— the file does not intersect the AOI (or is fully masked)."
                )
        except RuntimeError:
            raise
        except Exception:
            pass  # statistics unavailable — let the pipeline try anyway
        finally:
            chk = None

        return output_path


__all__ = ["LocalDEMSource", "assign_local_ids", "_COMMON_DEM_EXTENSIONS"]
