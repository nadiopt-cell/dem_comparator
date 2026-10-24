"""Main dialog for the DEM Comparator plugin.

Wraps ``ui/main_dialog.ui`` (loaded via ``uic.loadUiType``) and exposes
Qt signals consumed by :mod:`.draw_rectangle_tool` and :mod:`plugin`.

The class is intentionally small: it stores widget references, wires the
``draw on map`` button to the rectangle tool, and exposes helpers
(:meth:`selected_sources`, :meth:`selected_resolution_m`, …) that the
controller uses to build run parameters.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from qgis.PyQt import uic
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QCloseEvent
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
)

from qgis.core import QgsSettings

from ..core.align import RESAMPLING_BILINEAR, RESAMPLING_CUBIC, RESAMPLING_NEAREST
from ..core.debug_log import log, log_error
from ..i18n import apply_translations, tr
from ..sources.local import assign_local_ids
from ..sources.registry import available_sources

_FORM, _BASE = uic.loadUiType(os.path.join(os.path.dirname(__file__), "main_dialog.ui"))


# Mapping between dialog widget object names and DEM source ids.
_SOURCE_CHECKBOX = {
    "chkFabdem": "fabdem",
    "chkGlo30": "glo30",
    "chkNasadem": "nasadem",
    "chkAw3d30": "aw3d30",
    "chkSrtm": "srtm",
}

# QgsSettings (section Plugins) group used to persist dialog state between
# QGIS sessions.
_SETTINGS_GROUP = "dem_comparator"


@dataclass
class DialogState:
    """Snapshot of all user-visible parameters."""

    extent_mode: str            # "canvas" | "layer" | "drawn" | "manual"
    extent_rect: Optional[Tuple[float, float, float, float]]  # (xmin, ymin, xmax, ymax) or None
    extent_crs_authid: Optional[str]      # authid of the source CRS
    selected_sources: List[str]
    local_paths: List[str]               # local DEM rasters (issue #4)
    resolution_m: float
    resampling: str
    comparison_mode: str         # "all" | "reference"
    reference_source: Optional[str]
    output_dir: str


class DEMComparatorDialog(QDialog, _FORM):
    """The only QDialog in the plugin."""

    runRequested = pyqtSignal()
    cancelRequested = pyqtSignal()
    drawRectangleRequested = pyqtSignal()
    extentChanged = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setupUi(self)

        # Pre-fill defaults: 30 m, bilinear, canvas, all-pairs.
        self.cmbExtentMode.setCurrentIndex(0)
        self.cmbResolution.setCurrentIndex(1)
        self.cmbResampling.setCurrentIndex(0)
        self.cmbCompareMode.setCurrentIndex(0)

        # Reference combobox is populated when sources are toggled.
        self.cmbReference.setEnabled(False)
        self.cmbCompareMode.currentIndexChanged.connect(self._update_compare_mode)
        self.cmbExtentMode.currentIndexChanged.connect(self._update_extent_mode)

        # Manual extent editing only enabled in "Manual" mode.
        for w in (
            self.sbXMin, self.sbXMax, self.sbYMin, self.sbYMax
        ):
            w.setEnabled(False)
            w.valueChanged.connect(self._emit_extent_changed)

        self.btnBrowseOutput.clicked.connect(self._choose_output_dir)
        self.btnRun.clicked.connect(self.runRequested.emit)
        self.btnCancel.clicked.connect(self.cancelRequested.emit)
        self.btnClose.clicked.connect(self.reject)
        self.btnDrawRectangle.clicked.connect(self.drawRectangleRequested.emit)

        # Local DEM files (issue #4).
        self.btnAddLocal.clicked.connect(self._add_local_files)
        self.btnRemoveLocal.clicked.connect(self._remove_local_files)

        # Source checkboxes keep the reference combo in sync.
        for name in _SOURCE_CHECKBOX:
            chk: QCheckBox = getattr(self, name)
            chk.toggled.connect(self._rebuild_reference_choices)
        self._rebuild_reference_choices()

        self._last_drawn_extent: Optional[Tuple[float, float, float, float, str]] = None

        # Restore the last session's choices (output dir, sources, …).
        self.load_settings()

        # Persist on every run and when the dialog is closed.
        self.btnRun.clicked.connect(self.save_settings)

        # Russian UI (issue #7): rewrite widget texts when the QGIS locale
        # is Russian. Runs last so restored values are covered too.
        apply_translations(self)

    # -------------------------------------------------------------- state
    def state(self) -> DialogState:
        mode = self.extent_mode()
        rect = self._current_extent_rect()
        crs = self._current_extent_crs_authid()
        log(f"DialogState: mode={mode}, rect={rect}, crs={crs}")
        return DialogState(
            extent_mode=mode,
            extent_rect=rect,
            extent_crs_authid=crs,
            selected_sources=self.selected_sources(),
            local_paths=self.local_dem_paths(),
            resolution_m=self.selected_resolution_m(),
            resampling=self.selected_resampling(),
            comparison_mode=self.comparison_mode(),
            reference_source=self.selected_reference_source(),
            output_dir=self.output_dir(),
        )

    # ----------------------------------------------------------- accessors
    def extent_mode(self) -> str:
        return ("canvas", "layer", "drawn", "manual")[self.cmbExtentMode.currentIndex()]

    def selected_sources(self) -> List[str]:
        out = []
        for widget_name, source_id in _SOURCE_CHECKBOX.items():
            chk: QCheckBox = getattr(self, widget_name)
            if chk.isChecked():
                out.append(source_id)
        return out

    def local_dem_paths(self) -> List[str]:
        """Absolute paths of the local DEM rasters added by the user."""
        return [
            self.listLocalDems.item(i).text()
            for i in range(self.listLocalDems.count())
        ]

    def selected_resolution_m(self) -> float:
        return (10.0, 30.0, 90.0)[self.cmbResolution.currentIndex()]

    def selected_resampling(self) -> str:
        return (
            RESAMPLING_BILINEAR,
            RESAMPLING_CUBIC,
            RESAMPLING_NEAREST,
        )[self.cmbResampling.currentIndex()]

    def comparison_mode(self) -> str:
        return ("all", "reference")[self.cmbCompareMode.currentIndex()]

    def selected_reference_source(self) -> Optional[str]:
        if self.comparison_mode() != "reference":
            return None
        if self.cmbReference.count() == 0:
            return None
        return self.cmbReference.currentData()

    def output_dir(self) -> str:
        return self.leOutputDir.text().strip()

    def set_output_dir(self, path: str) -> None:
        self.leOutputDir.setText(path)

    def set_extent_from_user_draw(
        self,
        rect: Tuple[float, float, float, float],
        source_crs_authid: str,
    ) -> None:
        """Called by the draw tool after the user finishes a rectangle."""
        xmin, ymin, xmax, ymax = rect
        log(f"set_extent_from_user_draw: rect=({xmin}, {ymin}, {xmax}, {ymax}), crs={source_crs_authid}")
        try:
            self._last_drawn_extent = (xmin, ymin, xmax, ymax, source_crs_authid)
            log(f"_last_drawn_extent set to {self._last_drawn_extent}")
            self.cmbExtentMode.setCurrentIndex(2)  # "Drawn on map"
            log("cmbExtentMode set to 2 (Drawn on map)")
            self._update_extent_mode()
            self._emit_extent_changed()
        except Exception as exc:
            log_error(f"set_extent_from_user_draw failed: {exc}", exc)

    # ------------------------------------------------------- local files
    def _add_local_files(self) -> None:
        """Pick one or more local DEM rasters and add them to the list."""
        files, _filter = QFileDialog.getOpenFileNames(
            self,
            tr("Select DEM rasters"),
            "",
            tr("GeoTIFF rasters (*.tif *.tiff *.gtiff *.TIF *.TIFF);;All files (*)"),
        )
        existing = set(self.local_dem_paths())
        added = 0
        for path in files:
            path = os.path.abspath(path)
            if path not in existing:
                self.listLocalDems.addItem(path)
                existing.add(path)
                added += 1
        if added:
            self._rebuild_reference_choices()

    def _remove_local_files(self) -> None:
        """Remove the currently selected local rasters from the list."""
        removed = False
        for item in self.listLocalDems.selectedItems():
            self.listLocalDems.takeItem(self.listLocalDems.row(item))
            removed = True
        if removed:
            self._rebuild_reference_choices()

    # -------------------------------------------------- settings persistence
    def load_settings(self) -> None:
        """Restore the last saved dialog state from QgsSettings (if any)."""
        try:
            s = QgsSettings()
            section = QgsSettings.Plugins
            g = _SETTINGS_GROUP

            saved_dir = s.value(f"{g}/output_dir", "", type=str, section=section)
            if saved_dir:
                self.set_output_dir(saved_dir)

            # Local DEM file list (issue #4): stored as a string list.
            try:
                saved_paths = s.value(f"{g}/local_paths", [], type=list, section=section) or []
                self.listLocalDems.clear()
                for path in saved_paths:
                    if isinstance(path, str) and path:
                        self.listLocalDems.addItem(path)
            except Exception:
                pass

            for widget_name, source_id in _SOURCE_CHECKBOX.items():
                key = f"{g}/src_{source_id}"
                if s.contains(key, section=section):
                    chk: QCheckBox = getattr(self, widget_name)
                    chk.setChecked(s.value(key, False, type=bool, section=section))

            self.cmbResolution.setCurrentIndex(
                s.value(f"{g}/resolution_idx", 1, type=int, section=section)
            )
            self.cmbResampling.setCurrentIndex(
                s.value(f"{g}/resampling_idx", 0, type=int, section=section)
            )
            self.cmbCompareMode.setCurrentIndex(
                s.value(f"{g}/compare_mode_idx", 0, type=int, section=section)
            )

            # Restore the reference DEM only if it is among the selected ones.
            self._rebuild_reference_choices()
            ref_id = s.value(f"{g}/reference_id", "", type=str, section=section)
            if ref_id:
                idx = self.cmbReference.findData(ref_id)
                if idx >= 0:
                    self.cmbReference.setCurrentIndex(idx)

            self._update_compare_mode()
            self._update_extent_mode()
        except Exception as exc:  # settings must never break the dialog
            log_error(f"load_settings failed: {exc}", exc)

    def save_settings(self) -> None:
        """Persist the current dialog state to QgsSettings."""
        try:
            s = QgsSettings()
            section = QgsSettings.Plugins
            g = _SETTINGS_GROUP

            s.setValue(f"{g}/output_dir", self.output_dir(), section=section)
            s.setValue(f"{g}/local_paths", self.local_dem_paths(), section=section)
            for widget_name, source_id in _SOURCE_CHECKBOX.items():
                chk: QCheckBox = getattr(self, widget_name)
                s.setValue(f"{g}/src_{source_id}", chk.isChecked(), section=section)
            s.setValue(f"{g}/resolution_idx", self.cmbResolution.currentIndex(), section=section)
            s.setValue(f"{g}/resampling_idx", self.cmbResampling.currentIndex(), section=section)
            s.setValue(f"{g}/compare_mode_idx", self.cmbCompareMode.currentIndex(), section=section)
            ref = self.selected_reference_source() or ""
            s.setValue(f"{g}/reference_id", ref, section=section)
        except Exception as exc:  # settings must never break the dialog
            log_error(f"save_settings failed: {exc}", exc)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        self.save_settings()
        super().closeEvent(event)

    # -------------------------------------------------------- internals
    def _current_extent_rect(self):
        mode = self.extent_mode()
        if mode == "drawn" and self._last_drawn_extent is not None:
            xmin, ymin, xmax, ymax, _ = self._last_drawn_extent
            return (xmin, ymin, xmax, ymax)
        if mode == "manual":
            return (
                self.sbXMin.value(),
                self.sbYMin.value(),
                self.sbXMax.value(),
                self.sbYMax.value(),
            )
        return None

    def _current_extent_crs_authid(self) -> Optional[str]:
        mode = self.extent_mode()
        if mode == "drawn" and self._last_drawn_extent is not None:
            return self._last_drawn_extent[4]
        if mode == "manual":
            return "EPSG:4326"
        if mode == "canvas":
            # mainwindow has mapCanvas(); the dialog parents it loosely here
            try:
                from qgis.utils import iface

                return iface.mapCanvas().mapSettings().destinationCrs().authid()
            except Exception:
                return "EPSG:4326"
        if mode == "layer":
            try:
                from qgis.utils import iface

                layer = iface.activeLayer()
                if layer is not None:
                    return layer.crs().authid()
            except Exception:
                pass
        return "EPSG:4326"

    def _update_extent_mode(self) -> None:
        manual = self.extent_mode() == "manual"
        for w in (self.sbXMin, self.sbXMax, self.sbYMin, self.sbYMax):
            w.setEnabled(manual)
        self._update_extent_label()

    def _update_extent_label(self) -> None:
        rect = self._current_extent_rect()
        crs_authid = self._current_extent_crs_authid()
        if rect is None:
            self.lblExtent.setText(tr("No extent selected."))
        else:
            xmin, ymin, xmax, ymax = rect
            self.lblExtent.setText(
                tr("Extent [{crs}]: {x1}, {y1} – {x2}, {y2}").format(
                    crs=crs_authid,
                    x1=f"{xmin:.4f}", y1=f"{ymin:.4f}",
                    x2=f"{xmax:.4f}", y2=f"{ymax:.4f}",
                )
            )

    def _emit_extent_changed(self) -> None:
        self._update_extent_label()
        self.extentChanged.emit()

    def _update_compare_mode(self) -> None:
        single = self.comparison_mode() == "reference"
        self.cmbReference.setEnabled(single)

    def _rebuild_reference_choices(self) -> None:
        self.cmbReference.clear()
        for src_id in self.selected_sources():
            cls = next(c for c in available_sources() if c.id == src_id)
            self.cmbReference.addItem(f"{cls.name} [{src_id}]", src_id)
        # Local files (issue #4) join the reference candidates with the
        # same unique ids the plugin will build sources with.
        for path, sid in assign_local_ids(self.local_dem_paths()).items():
            self.cmbReference.addItem(
                f"{os.path.basename(path)} (local) [{sid}]", sid
            )

    def _choose_output_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, tr("Output directory"), self.output_dir())
        if chosen:
            self.set_output_dir(chosen)

    # --------------------------------------------------------- progress UI
    def set_progress(self, value: int, maximum: int = 100) -> None:
        self.progressBar.setMaximum(maximum)
        self.progressBar.setValue(value)

    def set_running(self, running: bool) -> None:
        self.btnRun.setEnabled(not running)
        self.btnCancel.setEnabled(running)
