"""Styling helpers for plugin-produced rasters.

Kept in a separate module so that :mod:`core.orchestrator` stays free of
QtGui imports at module import time (the renderer needs ``QColor``).

The difference rasters are Float32 with values around zero (``A - B``).
We render them with an interpolated *diverging* colour ramp:

- blue  (#2166ac) at the most negative value,
- near-white (#f7f7f7) at zero,
- red   (#b2182b) at the most positive value.

The ramp is symmetric around zero (``bound = max(|min|, |max|)``) so the
mid-tone always means "no difference" — exactly what SPEC 3.4 asks for
("blue = negative, red = positive").
"""
from __future__ import annotations

from typing import List

from qgis.core import (
    QgsColorRampShader,
    QgsRasterLayer,
    QgsRasterShader,
    QgsSingleBandPseudoColorRenderer,
)
from qgis.PyQt.QtGui import QColor

# Diverging RdBu-like palette (ColourBrewer "RdBu", colourblind safe).
_DIFF_NEG_COLOR = "#2166ac"
_DIFF_ZERO_COLOR = "#f7f7f7"
_DIFF_POS_COLOR = "#b2182b"

# Fallback half-width when a pair has no valid pixels (stats are NaN).
_DEFAULT_BOUND_M = 1.0


def diff_bound(diff_min: float, diff_max: float) -> float:
    """Return a symmetric half-width for the diverging ramp."""
    candidates = [abs(v) for v in (diff_min, diff_max) if v == v]  # drop NaN
    bound = max(candidates) if candidates else 0.0
    if bound <= 0.0:
        bound = _DEFAULT_BOUND_M
    return float(bound)


def diff_ramp_items(bound: float) -> List["QgsColorRampShader.ColorRampItem"]:
    """Build the three-stop interpolated ramp items for ``bound``."""
    return [
        QgsColorRampShader.ColorRampItem(
            -bound, QColor(_DIFF_NEG_COLOR), f"−{bound:.1f} m"
        ),
        QgsColorRampShader.ColorRampItem(
            0.0, QColor(_DIFF_ZERO_COLOR), "0"
        ),
        QgsColorRampShader.ColorRampItem(
            bound, QColor(_DIFF_POS_COLOR), f"+{bound:.1f} m"
        ),
    ]


def apply_diff_renderer(layer: QgsRasterLayer, diff_min: float, diff_max: float) -> None:
    """Style ``layer`` (a difference raster) with the diverging blue→red ramp."""
    bound = diff_bound(diff_min, diff_max)
    ramp = QgsColorRampShader()
    ramp.setColorRampType(QgsColorRampShader.Interpolated)
    ramp.setColorRampItemList(diff_ramp_items(bound))
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(ramp)
    renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
    layer.setRenderer(renderer)
    layer.triggerRepaint()


__all__ = ["apply_diff_renderer", "diff_bound", "diff_ramp_items"]
