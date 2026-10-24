"""Align multiple rasters to a single, shared grid.

The "common grid" is defined by:

- one CRS (EPSG:4326 — set in ``extent_utils.COMMON_CRS``);
- one resolution in CRS units (degrees) for that resolution, derived
  from a metric resolution using latitude-aware geodesic conversion
  (see :func:`make_aligner`);
- one extent (the union of all provided extents, optionally padded);
- one origin (top-left corner) so pixels stack up across rasters.

We deliberately rely on GDAL warp with ``gdal.Warp`` so we get correct
nodata handling and reprojection. The output is always a single-band
Float32 raster with a known nodata value (``-9999``).
"""
from __future__ import annotations

import math
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
        resolution_deg_y: Optional[float] = None,
    ) -> None:
        """``resolution_deg`` is the X (east-west) step; ``resolution_deg_y``
        defaults to the same value and can differ for latitude-aware grids
        (metres-per-degree along parallels differs from along meridians).
        """
        if resampling not in VALID_RESAMPLING:
            raise ValueError(f"Unsupported resampling: {resampling}")
        if resolution_deg <= 0:
            raise ValueError("resolution_deg must be > 0")
        if resolution_deg_y is not None and resolution_deg_y <= 0:
            raise ValueError("resolution_deg_y must be > 0")
        self.output_dir = output_dir
        self.resolution_deg = resolution_deg
        self.resolution_deg_y = (
            resolution_deg_y if resolution_deg_y is not None else resolution_deg
        )
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
            # Snap to the requested pixel resolution (X and Y steps may
            # differ on a latitude-aware grid).
            res_x = self.resolution_deg
            res_y = self.resolution_deg_y
            # Pad the union extent by extra_buffer_pixels on every side (so
            # edge pixels get resampling context), then extend the padded
            # bounds outward so each span is an EXACT integer multiple of
            # the resolution. gdal.Warp derives the output pixel size as
            # span/size when both outputBounds and width/height are given;
            # with span == size * res the pixel size is therefore exactly
            # the requested resolution instead of being silently shrunk.
            pad_x = self.extra_buffer_pixels * res_x
            pad_y = self.extra_buffer_pixels * res_y
            xmin_p, ymin_p = xmin - pad_x, ymin - pad_y
            xmax_p, ymax_p = xmax + pad_x, ymax + pad_y
            width = max(1, int(math.ceil((xmax_p - xmin_p) / res_x - 1e-9)))
            height = max(1, int(math.ceil((ymax_p - ymin_p) / res_y - 1e-9)))
            xmax_p = xmin_p + width * res_x
            ymax_p = ymin_p + height * res_y

            return Grid(
                crs=COMMON_CRS.authid(),
                extent=(xmin_p, ymin_p, xmax_p, ymax_p),
                width=width,
                height=height,
                pixel_size_x=res_x,
                pixel_size_y=-res_y,
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



# --------------------------------------------------------------------- geodesy


def metres_per_degree_latitude(lat_deg: float) -> float:
    """Metres per one degree of latitude at ``lat_deg`` (WGS84 approx).

    Accurate series expansion (error < 1 m over ±90°):
    111132.92 − 559.82·cos(2φ) + 1.175·cos(4φ) − 0.0023·cos(6φ).
    """
    phi = math.radians(lat_deg)
    return (
        111_132.92
        - 559.82 * math.cos(2.0 * phi)
        + 1.175 * math.cos(4.0 * phi)
        - 0.0023 * math.cos(6.0 * phi)
    )


def metres_per_degree_longitude(lat_deg: float) -> float:
    """Metres per one degree of longitude at ``lat_deg`` (WGS84 approx).

    Accurate series expansion (error < 1 m over ±90°):
    111412.84·cos(φ) − 93.5·cos(3φ) + 0.118·cos(5φ).
    Returns ~111.32 km at the equator and ~55.8 km at 60°.
    """
    phi = math.radians(lat_deg)
    return (
        111_412.84 * math.cos(phi)
        - 93.5 * math.cos(3.0 * phi)
        + 0.118 * math.cos(5.0 * phi)
    )


# Latitude beyond which the longitude conversion is clamped (cos(lat) gets
# too small near the poles and any tiny error explodes into huge degree
# steps). No global DEM covers ±82°+ anyway.
_MAX_SAFE_CENTRE_LAT = 82.0


def make_aligner(
    output_dir: str,
    resolution_m: float,
    resampling: str = RESAMPLING_BILINEAR,
    centre_lat_deg: Optional[float] = None,
) -> Aligner:
    """Convert a metric resolution to degrees (for EPSG:4326).

    Two modes:

    - ``centre_lat_deg=None`` (legacy): one equatorial factor for both
      axes (111 320 m/deg). Kept for backward compatibility.
    - ``centre_lat_deg=<lat>`` (default for new runs): geodesic
      metres-per-degree evaluated at the AOI centre latitude, separately
      for X and Y, so the ground sampling equals ``resolution_m`` on the
      ground at the centre of the study area instead of only at the
      equator.
    """
    if centre_lat_deg is None:
        resolution_deg = resolution_m / 111_320.0
        return Aligner(output_dir, resolution_deg=resolution_deg, resampling=resampling)

    lat = max(-_MAX_SAFE_CENTRE_LAT, min(_MAX_SAFE_CENTRE_LAT, centre_lat_deg))
    res_deg_x = resolution_m / metres_per_degree_longitude(lat)
    res_deg_y = resolution_m / metres_per_degree_latitude(lat)
    return Aligner(
        output_dir,
        resolution_deg=res_deg_x,
        resolution_deg_y=res_deg_y,
        resampling=resampling,
    )
