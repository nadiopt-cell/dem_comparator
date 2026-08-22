"""Extent / CRS helpers shared by the plugin.

Why a dedicated module:
- Plugins receive user extents in many CRSes (project CRS, layer CRS, or
  hand-drawn rectangle in the canvas CRS). All comparisons, downloads and
  writing must happen in a single, predictable grid (EPSG:4326 in this MVP).
- Several sources have coverage limits (e.g. SRTM is between -60° and 60°
  latitude). A single helper makes those checks easy to implement.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCoordinateTransformContext,
    QgsGeometry,
    QgsRectangle,
)

# Single source of truth for the common grid CRS used throughout the plugin.
COMMON_CRS = QgsCoordinateReferenceSystem("EPSG:4326")

# We use robust Earth radius (m) to pad extents generously when needed.
EARTH_RADIUS_M = 6_378_137.0


@dataclass(frozen=True)
class ExtentInfo:
    """Convenience container for an extent + its source CRS."""

    rectangle: QgsRectangle
    crs: QgsCoordinateReferenceSystem

    def transformed(
        self,
        target_crs: QgsCoordinateReferenceSystem,
        context: Optional[QgsCoordinateTransformContext] = None,
    ) -> "ExtentInfo":
        """Return a new ExtentInfo in ``target_crs``."""
        if self.crs == target_crs:
            return self
        ctx = context or QgsCoordinateTransformContext()
        xform = QgsCoordinateTransform(self.crs, target_crs, ctx)
        new_rect = xform.transformBoundingBox(self.rectangle)
        return ExtentInfo(new_rect, target_crs)


def extract_extent_from_canvas(iface) -> ExtentInfo:
    """Read the current map canvas extent."""
    canvas = iface.mapCanvas()
    return ExtentInfo(canvas.extent(), canvas.mapSettings().destinationCrs())


def extract_extent_from_layer(layer) -> ExtentInfo:
    """Read the extent of ``layer`` (assumed to be a vector layer)."""
    if layer is None or not layer.isValid():
        raise ValueError("Invalid layer")
    return ExtentInfo(layer.extent(), layer.crs())


def clamp_to_global(rect: QgsRectangle) -> QgsRectangle:
    """Clamp rectangle to valid geographic bounds in EPSG:4326."""
    out = QgsRectangle(rect)
    out.setXMinimum(max(out.xMinimum(), -180.0))
    out.setXMaximum(min(out.xMaximum(), 180.0))
    out.setYMinimum(max(out.yMinimum(), -90.0))
    out.setYMaximum(min(out.yMaximum(), 90.0))
    return out


def expand_to_min_size(rect: QgsRectangle, min_size_deg: float) -> QgsRectangle:
    """Ensure at least ``min_size_deg`` in both width and height (in degrees)."""
    out = QgsRectangle(rect)
    if out.width() < min_size_deg:
        cx = (out.xMinimum() + out.xMaximum()) / 2.0
        out.setXMinimum(cx - min_size_deg / 2.0)
        out.setXMaximum(cx + min_size_deg / 2.0)
    if out.height() < min_size_deg:
        cy = (out.yMinimum() + out.yMaximum()) / 2.0
        out.setYMinimum(cy - min_size_deg / 2.0)
        out.setYMaximum(cy + min_size_deg / 2.0)
    return out


def to_common_grid(extent: ExtentInfo) -> ExtentInfo:
    """Transform any extent to EPSG:4326 and clamp to valid bounds."""
    transformed = extent.transformed(COMMON_CRS)
    return ExtentInfo(clamp_to_global(transformed.rectangle), COMMON_CRS)


def merge_extents(extents: Iterable[ExtentInfo]) -> Optional[ExtentInfo]:
    """Compute the union of several extents, returned in the common grid CRS."""
    rects = [e.rectangle for e in extents if e is not None]
    if not rects:
        return None
    out = QgsRectangle(rects[0])
    for r in rects[1:]:
        out.combineExtentWith(r)
    return ExtentInfo(out, COMMON_CRS)


def extent_to_geometry(rect: QgsRectangle) -> QgsGeometry:
    """Convert a rectangle to a polygon geometry (useful for layer masks)."""
    return QgsGeometry.fromRect(rect)
