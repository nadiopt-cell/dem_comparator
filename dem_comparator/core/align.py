"""Align multiple rasters to a single, shared grid.

The "common grid" is defined by:

- one CRS (EPSG:4326 — set in ``extent_utils.COMMON_CRS``);
- one resolution in CRS units (degrees) for that resolution;
- one extent (the union of all provided extents, optionally padded);
- one origin (top-left corner) so pixels stack up across rasters.

We deliberately rely on GDAL warp with ``gdal.Warp`` so we get correct
nodata handling and reprojection. The output is always a single-band
Float32 raster with a known nodata value (``-9999``).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, List, Optional

from osgeo import gdal

from .extent_utils import COMMON_CRS

# Default nodata value carried by every aligned raster.
NODATA = -9999.0

# Supported resampling methods (passed to gdal Warp).
RESAMPLING_BILINEAR = "bilinear"
RESAMPLING_CUBIC = "cubic"
RESAMPLING_NEAREST = "near"

VALID_RESAMPLING = {
    RESAMPLING_BILINEAR,
    RESAMPLING_CUBIC,
    RESAMPLING_NEAREST,
}


@dataclass
class RasterSpec:
    """Description of a raster to be aligned."""

    label: str            # user-visible name (e.g. "FABDEM")
    path: str             # absolute path to the source GeoTIFF
    output_path: str      # absolute path for the aligned GeoTIFF

    def __post_init__(self) -> None:
        if not os.path.exists(self.path):
            raise FileNotFoundError(self.path)


@dataclass
class Grid:
    """The shared grid computed by :class:`Aligner`."""

    crs: str
    extent: tuple        # (xmin, ymin, xmax, ymax) in CRS units
    width: int
    height: int
    pixel_size_x: float
    pixel_size_y: float


class Aligner:
    """Compute the shared grid and write aligned rasters to disk."""

    def __init__(
        self,
        output_dir: str,
        resolution_deg: float,
        resampling: str = RESAMPLING_BILINEAR,
        extra_buffer_pixels: int = 1,
    ) -> None:
        if resampling not in VALID_RESAMPLING:
            raise ValueError(f"Unsupported resampling: {resampling}")
        if resolution_deg <= 0:
            raise ValueError("resolution_deg must be > 0")
        self.output_dir = output_dir
        self.resolution_deg = resolution_deg
        self.resampling = resampling
        self.extra_buffer_pixels = extra_buffer_pixels
        os.makedirs(self.output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    def compute_grid(self, specs: Iterable[RasterSpec]) -> Grid:
        """Compute the union extent and a matching width/height in the common CRS."""
        ds = None
        try:
            total_extent = [float("inf"), float("inf"), float("-inf"), float("-inf")]
            for spec in specs:
                ds = gdal.Open(spec.path, gdal.GA_ReadOnly)
                if ds is None:
                    raise RuntimeError(f"Cannot open raster: {spec.path}")
                gt = ds.GetGeoTransform()
                rx, ry = gt[1], gt[5]    # pixel size, can be negative
                cols, rows = ds.RasterXSize, ds.RasterYSize
                x0, y0 = gt[0], gt[3]
                x1 = x0 + cols * rx
                y1 = y0 + rows * ry
                if rx < 0:
                    x0, x1 = x1, x0
                if ry < 0:
                    y0, y1 = y1, y0
                total_extent[0] = min(total_extent[0], x0)
                total_extent[1] = min(total_extent[1], y0)
                total_extent[2] = max(total_extent[2], x1)
                total_extent[3] = max(total_extent[3], y1)
                ds = None  # close this iteration
            if total_extent[0] == float("inf"):
                raise RuntimeError("No rasters supplied")

            xmin, ymin, xmax, ymax = total_extent
            # Snap to the requested pixel resolution.
            res = self.resolution_deg
            width = int(round((xmax - xmin) / res)) + 1 + 2 * self.extra_buffer_pixels
            height = int(round((ymax - ymin) / res)) + 1 + 2 * self.extra_buffer_pixels

            return Grid(
                crs=COMMON_CRS.authid(),
                extent=(xmin, ymin, xmax, ymax),
                width=width,
                height=height,
                pixel_size_x=res,
                pixel_size_y=-res,
            )
        finally:
            if ds is not None:
                ds = None

    # ------------------------------------------------------------------
    def align(self, specs: List[RasterSpec], grid: Grid) -> List[str]:
        """Warp every raster onto ``grid``. Returns the list of output paths."""
        out_paths: List[str] = []
        gdal.UseExceptions()
        for spec in specs:
            try:
                gdal.Warp(
                    spec.output_path,
                    spec.path,
                    format="GTiff",
                    dstSRS=grid.crs,
                    outputBounds=list(grid.extent),
                    width=grid.width,
                    height=grid.height,
                    resampleAlg=self.resampling,
                    dstNodata=NODATA,
                    srcNodata=NODATA,
                    multithread=True,
                    creationOptions=[
                        "COMPRESS=DEFLATE",
                        "TILED=YES",
                        "BIGTIFF=IF_SAFER",
                    ],
                )
            except Exception as exc:
                raise RuntimeError(f"Failed to align {spec.label}: {exc}") from exc
            out_paths.append(spec.output_path)
        return out_paths


def make_aligner(
    output_dir: str,
    resolution_m: float,
    resampling: str = RESAMPLING_BILINEAR,
    at_equator_m_per_deg: float = 111_320.0,
) -> Aligner:
    """Convert a metric resolution to degrees (for EPSG:4326)."""
    resolution_deg = resolution_m / at_equator_m_per_deg
    return Aligner(output_dir, resolution_deg=resolution_deg, resampling=resampling)
