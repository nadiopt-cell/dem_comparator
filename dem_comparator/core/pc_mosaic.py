"""Mosaic + clip helper for Planetary Computer items.

PC STAC queries usually return several COG items that together cover the
requested bbox. To produce a single raster we:

1. Stream each signed COG into a VRT (cheap, no full download);
2. Wrap the VRTs in a parent VRT (mosaic);
3. Warp that VRT to ``output_path`` with the requested bbox, CRS and
   output resolution.

All operations go through GDAL (``/vsimem/`` + ``gdal.Warp``) so we never
materialise the full set of tiles on disk — only the final clipped GeoTIFF.
"""
from __future__ import annotations

import os
import tempfile
from typing import Iterable, List, Optional, Tuple

from osgeo import gdal, osr

from .align import NODATA

# Use a single-threaded warp at warp-time, but multi-threaded I/O inside.
_DEFAULT_CREATION_OPTIONS = ["COMPRESS=DEFLATE", "TILED=YES", "BIGTIFF=IF_SAFER"]


def build_vrt_for_items(
    signed_hrefs: Iterable[str],
) -> str:
    """Return a VRT path that mosaics all ``signed_hrefs`` (COGs / TIFs)."""
    hrefs = list(signed_hrefs)
    if not hrefs:
        raise ValueError("No items to mosaic.")
    tmp_dir = tempfile.mkdtemp(prefix="dem_cmp_vrt_")
    vrt_path = os.path.join(tmp_dir, "mosaic.vrt")
    gdal.UseExceptions()
    gdal.BuildVRT(vrt_path, hrefs, srcNodata=NODATA, VRTNodata=NODATA)
    return vrt_path


def warp_to_output(
    vrt_path: str,
    output_path: str,
    bbox_wgs84: Tuple[float, float, float, float],
    resolution_deg: float,
    resampling: str = "bilinear",
) -> str:
    """Warp ``vrt_path`` to ``output_path`` clipped to ``bbox_wgs84``.

    :param vrt_path: input VRT or raster.
    :param output_path: destination GeoTIFF.
    :param bbox_wgs84: (xmin, ymin, xmax, ymax) in EPSG:4326 degrees.
    :param resolution_deg: output pixel size in degrees.
    :param resampling: GDAL resampling algorithm name.
    :returns: ``output_path``.
    """
    gdal.UseExceptions()
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    warp_options = gdal.WarpOptions(
        format="GTiff",
        dstSRS="EPSG:4326",
        outputBounds=list(bbox_wgs84),
        xRes=resolution_deg,
        yRes=resolution_deg,
        resampleAlg=_normalize_resampling(resampling),
        dstNodata=NODATA,
        srcNodata=NODATA,
        multithread=True,
        creationOptions=_DEFAULT_CREATION_OPTIONS,
    )
    gdal.Warp(output_path, vrt_path, options=warp_options)
    return output_path


def _normalize_resampling(name: str) -> str:
    """Map plugin names onto GDAL's resampling enum."""
    table = {
        "bilinear": "bilinear",
        "cubic": "cubic",
        "nearest": "near",
        "near": "near",
    }
    return table.get(name.lower(), "bilinear")


def cleanup_vrt(vrt_path: str) -> None:
    """Best-effort cleanup of VRT and any sibling files."""
    if not vrt_path or not os.path.exists(vrt_path):
        return
    tmp_dir = os.path.dirname(vrt_path)
    try:
        for entry in os.listdir(tmp_dir):
            os.remove(os.path.join(tmp_dir, entry))
        os.rmdir(tmp_dir)
    except OSError:
        pass


__all__ = ["build_vrt_for_items", "warp_to_output", "cleanup_vrt"]