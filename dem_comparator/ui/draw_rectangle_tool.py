"""Map tool that draws an axis-aligned rectangle on the canvas.

Used by the main dialog button "Draw on map". Emits
:attr:`DrawnRectangleTool.extentDrawn` with the rectangle in the
canvas's CRS (typically project CRS) when the user finishes a drag.

The tool uses QGIS's built-in rectangle rubber band, so no third-party
dependency is required.
"""
from __future__ import annotations

from qgis.core import QgsPointXY, QgsRectangle, QgsWkbTypes
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor

from ..core.debug_log import log, log_error


class DrawnRectangleTool(QgsMapTool):
    """Map tool: click and drag to define a rectangle."""

    extentDrawn = pyqtSignal(object, str)   # (QgsRectangle, crs.authid())

    def __init__(self, canvas) -> None:
        super().__init__(canvas)
        self.canvas = canvas
        self._rubber: QgsRubberBand | None = None
        self._start_x: float | None = None
        self._start_y: float | None = None
        log("DrawnRectangleTool created", "tool")

    # ---------------------------------------------------------------- draw
    def canvasPressEvent(self, event) -> None:  # noqa: N802 - QGIS API
        if event.button() != Qt.LeftButton:
            return
        try:
            sp = self.toMapCoordinates(event.pos())
        except Exception as exc:
            log_error(f"toMapCoordinates failed: {exc}", exc, "tool")
            return
        log(f"canvasPressEvent: start=({sp.x():.2f}, {sp.y():.2f})", "tool")
        try:
            self._ensure_rubber()
            self._start_x = sp.x()
            self._start_y = sp.y()
            self._rubber.reset(QgsWkbTypes.PolygonGeometry)
            self._rubber.addPoint(sp)
            self._rubber.addPoint(sp)
            self._rubber.addPoint(sp)
            self._rubber.addPoint(sp)
            self._rubber.show()
        except Exception as exc:
            log_error(f"canvasPressEvent rubber failed: {exc}", exc, "tool")
            self._teardown()

    def canvasMoveEvent(self, event) -> None:  # noqa: N802 - QGIS API
        if self._rubber is None or self._start_x is None:
            log(f"canvasMoveEvent skipped: rubber={self._rubber is not None}, "
                f"start={self._start_x is not None}", "tool")
            return
        try:
            ep = self.toMapCoordinates(event.pos())
            x0, y0 = self._start_x, self._start_y
            x1, y1 = ep.x(), ep.y()
            log(f"canvasMoveEvent: ({x1:.4f}, {y1:.4f})", "tool")
            corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
            for i, (px, py) in enumerate(corners):
                self._rubber.movePoint(i, _pt(px, py))
        except Exception as exc:
            log_error(f"canvasMoveEvent failed: {exc}", exc, "tool")

    def canvasReleaseEvent(self, event) -> None:  # noqa: N802 - QGIS API
        log("canvasReleaseEvent called", "tool")
        if self._rubber is None or self._start_x is None:
            log(f"canvasReleaseEvent skipped: rubber={self._rubber is not None}, "
                f"start={self._start_x is not None}", "tool")
            return
        try:
            ep = self.toMapCoordinates(event.pos())
            rect = QgsRectangle(
                min(self._start_x, ep.x()),
                min(self._start_y, ep.y()),
                max(self._start_x, ep.x()),
                max(self._start_y, ep.y()),
            )
            crs_authid = self.canvas.mapSettings().destinationCrs().authid()
            log(f"canvasReleaseEvent: rect=({rect.xMinimum():.4f}, {rect.yMinimum():.4f}, "
                f"{rect.xMaximum():.4f}, {rect.yMaximum():.4f}), crs={crs_authid}", "tool")
            # Простой клик без перемещения — игнорируем
            if rect.width() < 0.0001 and rect.height() < 0.0001:
                log("canvasReleaseEvent: zero-area rect (click without drag), ignoring", "tool")
                self._teardown()
                return
            self.extentDrawn.emit(rect, crs_authid)
        except Exception as exc:
            log_error(f"canvasReleaseEvent failed: {exc}", exc, "tool")
        self._teardown()

    def deactivate(self) -> None:
        log("DrawnRectangleTool deactivated", "tool")
        self._teardown()
        super().deactivate()

    # --------------------------------------------------------------- utils
    def _ensure_rubber(self) -> None:
        if self._rubber is not None:
            return
        self._rubber = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry)
        self._rubber.setStrokeColor(QColor(255, 80, 80, 200))
        fill = QColor(255, 80, 80, 40)
        self._rubber.setFillColor(fill)
        self._rubber.setWidth(2)
        self._rubber.setIconSize(0)  # отключаем иконки на вершинах
        self._rubber.setVisible(True)
        self.canvas.refresh()

    def _teardown(self) -> None:
        if self._rubber is not None:
            self._rubber.hide()
            self._rubber.reset(QgsWkbTypes.PolygonGeometry)
            self._rubber = None
        self._start_x = None
        self._start_y = None


def _pt(x: float, y: float) -> "QgsPointXY":
    return QgsPointXY(x, y)
