"""DEM Comparator - main plugin class.

Wires together the dialog, the rectangle draw tool, the background task,
and the post-processing steps (add layers, write report).
"""
from __future__ import annotations

import os
from typing import Optional

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsProject,
    QgsRectangle,
)
from qgis.gui import QgisInterface
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.PyQt.QtCore import QUrl

from .core.debug_log import log, log_error, log_warn, log_variable
from .core.extent_utils import (
    COMMON_CRS,
    ExtentInfo,
    extract_extent_from_canvas,
    extract_extent_from_layer,
)
from .core.task import DemComparatorTask
from .i18n import tr
from .sources.base import default_source_cache_dir
from .sources.local import LocalDEMSource, assign_local_ids
from .sources.registry import build_shared_pc_client, get_source
from .ui.draw_rectangle_tool import DrawnRectangleTool
from .ui.main_dialog import DEMComparatorDialog


# User-visible layer group name for the run's outputs.
RESULTS_GROUP = "DEM Comparator Results"


class DEMComparatorPlugin:
    """QGIS plugin lifecycle: initGui / unload."""

    def __init__(self, iface: QgisInterface) -> None:
        self.iface = iface
        self.action: QAction | None = None
        self._menu = "&DEM Comparator"
        self._toolbar = self.iface.addToolBar("DEM Comparator")
        self._toolbar.setObjectName("DEMComparatorToolbar")
        self._dialog: Optional[DEMComparatorDialog] = None
        self._draw_tool: Optional[DrawnRectangleTool] = None
        self._task: Optional[DemComparatorTask] = None

    # ------------------------------------------------------------------ init
    def initGui(self) -> None:
        self.action = QAction(
            self._icon(),
            tr("Open DEM Comparator"),
            self.iface.mainWindow(),
        )
        self.action.setStatusTip(tr("Compare several global DEMs on the same area"))
        self.action.triggered.connect(self._on_run_clicked)
        self.iface.addPluginToRasterMenu(self._menu, self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self) -> None:
        if self.action is None:
            return
        self.iface.removePluginRasterMenu(self._menu, self.action)
        self.iface.removeToolBarIcon(self.action)
        del self.action
        self.action = None
        # Detach the dialog if it's open.
        if self._dialog is not None:
            self._dialog.close()
            self._dialog = None
        # Make sure we deactivate the rectangle tool if it's active.
        if self._draw_tool is not None and self.iface.mapCanvas().mapTool() is self._draw_tool:
            self.iface.mapCanvas().unsetMapTool(self._draw_tool)
        self._draw_tool = None

    # --------------------------------------------------------------- entry
    def _on_run_clicked(self) -> None:
        log("DEM Comparator dialog opened")
        if self._dialog is None:
            self._dialog = DEMComparatorDialog(self.iface.mainWindow())
            self._dialog.runRequested.connect(self._start_pipeline)
            self._dialog.cancelRequested.connect(self._cancel_pipeline)
            self._dialog.drawRectangleRequested.connect(self._activate_draw_tool)
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()

    # -------------------------------------------------------------- canvas
    def _activate_draw_tool(self) -> None:
        log("Activating draw-on-map tool")
        if self._draw_tool is None:
            self._draw_tool = DrawnRectangleTool(self.iface.mapCanvas())
            self._draw_tool.extentDrawn.connect(self._on_extent_drawn)
        self.iface.mapCanvas().setMapTool(self._draw_tool)

    def _on_extent_drawn(self, rect: QgsRectangle, crs_authid: str) -> None:
        log(f"Extent drawn: rect=({rect.xMinimum():.4f}, {rect.yMinimum():.4f}, "
            f"{rect.xMaximum():.4f}, {rect.yMaximum():.4f}), crs={crs_authid}")
        if self._dialog is None:
            log_warn("Extent drawn but no dialog — ignoring")
            return
        bbox = (rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum())
        log(f"Calling set_extent_from_user_draw(bbox={bbox}, crs={crs_authid})")
        self._dialog.set_extent_from_user_draw(bbox, crs_authid)

    # ----------------------------------------------------------- pipeline
    def _start_pipeline(self) -> None:
        log("Pipeline start requested")
        assert self._dialog is not None
        state = self._dialog.state()

        log_variable("selected_sources", state.selected_sources)
        log_variable("local_paths", state.local_paths)
        log_variable("extent_rect", state.extent_rect)
        log_variable("output_dir", state.output_dir)
        log_variable("resolution_m", state.resolution_m)
        log_variable("comparison_mode", state.comparison_mode)

        # ---- input validation
        if not state.selected_sources and not state.local_paths:
            log_warn("Validation: no sources selected")
            QMessageBox.warning(
                self._dialog, tr("DEM Comparator"), tr("Select at least one DEM source.")
            )
            return
        for path in state.local_paths:
            if not os.path.isfile(path):
                log_warn(f"Validation: local file not found: {path}")
                QMessageBox.warning(
                    self._dialog,
                    tr("DEM Comparator"),
                    tr("File not found: {path}").format(path=path),
                )
                return
        if state.extent_rect is None:
            log_warn("Validation: no extent")
            QMessageBox.warning(
                self._dialog, tr("DEM Comparator"), tr("No extent available.")
            )
            return
        if not state.output_dir:
            log_warn("Validation: no output dir")
            QMessageBox.warning(
                self._dialog, tr("DEM Comparator"), tr("Choose an output directory.")
            )
            return

        try:
            extent_info = self._build_extent_info(state)
            log(f"ExtentInfo: rect={extent_info.rectangle.toString()}, crs={extent_info.crs.authid()}")
        except Exception as exc:
            log_error(f"build_extent_info failed: {exc}", exc)
            QMessageBox.warning(
                self._dialog,
                tr("DEM Comparator"),
                tr("Invalid extent: {exc}").format(exc=exc),
            )
            return

        # ---- prepare sources (shared Planetary Computer client)
        log("Preparing sources")
        cache_root = default_source_cache_dir(self._cache_root())
        log_variable("cache_root", cache_root)
        pc_client = build_shared_pc_client(cache_root)
        sources = [
            get_source(sid, cache_root, pc_client=pc_client)
            for sid in state.selected_sources
        ]
        # Local rasters join the downloaded ones as pseudo-sources (issue #4).
        for path, sid in assign_local_ids(state.local_paths).items():
            sources.append(
                LocalDEMSource(path, source_id=sid, cache_root=cache_root,
                               pc_client=pc_client)
            )
        log(f"Sources ready: {[s.id for s in sources]}")

        # ---- output dir
        os.makedirs(state.output_dir, exist_ok=True)
        log(f"Output dir exists: {state.output_dir}")

        # ---- start background task
        self._dialog.set_running(True)
        self._dialog.set_progress(0, 100)

        self._task = DemComparatorTask(
            description=tr("DEM Comparator: download + align + compare"),
            output_dir=state.output_dir,
            sources=sources,
            extent=extent_info,
            resolution_m=state.resolution_m,
            resampling=state.resampling,
            comparison_mode=state.comparison_mode,
            reference_id=state.reference_source,
        )
        self._task.taskCompleted.connect(self._on_task_finished)
        self._task.taskTerminated.connect(self._on_task_failed)
        # Live progress: orchestrator -> feedback -> task -> dialog bar.
        self._task.progressChanged.connect(self._on_task_progress)
        # pipe progress messages into the dialog
        self._dialog.set_progress(5, 100)
        QgsApplication.taskManager().addTask(self._task)

    def _cancel_pipeline(self) -> None:
        if self._task is not None and not self._task.isCompleted():
            self._task.cancel()
            self.iface.messageBar().pushMessage(
                tr("DEM Comparator"), tr("Cancellation requested…"), level=2, duration=3
            )

    def _on_task_progress(self, percent: float) -> None:
        if self._dialog is not None:
            self._dialog.set_progress(int(percent), 100)

    # ------------------------------------------------------- task callbacks
    def _on_task_finished(self) -> None:
        if self._dialog is not None:
            self._dialog.set_running(False)
            self._dialog.set_progress(100, 100)
        if self._task is None:
            return

        # 1) Add layers to the project inside a group.
        group = self._ensure_group(tr(RESULTS_GROUP))
        added = 0
        for layer in self._task.aligned_layers:
            if layer.isValid():
                self._add_layer_to_group(group, layer)
                added += 1
        if self._task.comparison is not None:
            from .core.orchestrator import Orchestrator
            for dlayer in Orchestrator.diff_layers(self._task.comparison):
                self._add_layer_to_group(group, dlayer)
                added += 1

        # 2) Open the HTML report.
        if self._task.report_path and os.path.exists(self._task.report_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._task.report_path))
            self.iface.messageBar().pushMessage(
                tr("DEM Comparator"),
                tr("Done. {added} layers added. Report: {path}").format(
                    added=added, path=self._task.report_path
                ),
                level=0,
                duration=8,
            )

        self._task = None

    def _on_task_failed(self) -> None:
        if self._dialog is not None:
            self._dialog.set_running(False)
            self._dialog.set_progress(0, 100)
        if self._task is None:
            return
        if self._task.cancelled:
            # User pressed Cancel — not an error, tell them politely.
            self.iface.messageBar().pushMessage(
                tr("DEM Comparator"),
                tr("Run cancelled."),
                level=1,
                duration=5,
            )
        elif self._task.exception is not None:
            self.iface.messageBar().pushMessage(
                tr("DEM Comparator"),
                tr("Run failed: {exc}").format(exc=self._task.exception),
                level=2,
                duration=8,
            )
        self._task = None

    # -------------------------------------------------------------- helpers
    def _build_extent_info(self, state) -> ExtentInfo:
        """Translate the dialog state into an :class:`ExtentInfo`."""
        if state.extent_mode == "drawn":
            return ExtentInfo(
                rectangle=QgsRectangle(*state.extent_rect),
                crs=QgsCoordinateReferenceSystem(state.extent_crs_authid),
            )
        if state.extent_mode == "manual":
            return ExtentInfo(
                rectangle=QgsRectangle(*state.extent_rect),
                crs=COMMON_CRS,
            )
        if state.extent_mode == "layer":
            layer = self.iface.activeLayer()
            if layer is None:
                raise ValueError("No active vector layer.")
            return extract_extent_from_layer(layer)
        # canvas
        return extract_extent_from_canvas(self.iface)

    def _cache_root(self) -> str:
        """Return the cache root for downloaded DEM tiles."""
        profile = QgsApplication.qgisSettingsDir()
        return os.path.join(profile, "dem_comparator_cache")

    def _ensure_group(self, name: str):
        root = QgsProject.instance().layerTreeRoot()
        existing = root.findGroup(name)
        if existing is not None:
            return existing
        return root.addGroup(name)

    def _add_layer_to_group(self, group, layer) -> None:
        """Add ``layer`` into ``group`` without duplicating it in the root."""
        project = QgsProject.instance()
        if layer.id() in project.mapLayers():
            return
        project.addMapLayer(layer, False)
        group.addLayer(layer)

    def _icon(self):
        # Local import to avoid loading PyQt at import time.
        from qgis.PyQt.QtGui import QIcon
        import os
        icon_path = os.path.join(os.path.dirname(__file__), "icons", "icon.png")
        return QIcon(icon_path)
