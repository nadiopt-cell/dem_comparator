"""High-level orchestrator: downloads, aligns, compares, reports.

This module glues together the core utilities and the source registry.
It is deliberately synchronous: the long-running parts are wrapped by
:mod:`qgis.core.QgsTask` in :mod:`plugin`, so the UI thread is never blocked.

The orchestrator has no Qt dependency so it's easy to unit-test (mock the
sources).
"""
from __future__ import annotations

import os
from dataclasses import asdict
from typing import List, Optional, Tuple

from qgis.core import (
    QgsProcessingFeedback,
    QgsRasterLayer,
)

from .align import Aligner, RasterSpec, make_aligner
from .compare import Comparator, ComparisonResult
from .extent_utils import ExtentInfo, COMMON_CRS, to_common_grid
from .report import ReportGenerator
from ..sources.base import BaseDEMSource


class OrchestratorError(Exception):
    """Raised when an unrecoverable issue prevents running the pipeline."""


class OrchestratorCancelled(OrchestratorError):
    """Raised when the user cancels the run mid-pipeline.

    Subclasses :class:`OrchestratorError` so older callers that only catch
    the base class still work, but :class:`~core.task.DemComparatorTask`
    treats it specially ("cancelled" instead of "failed").
    """


# Progress checkpoints (percent) for the pipeline stages.
_PROGRESS_AFTER_AVAILABILITY = 5
_PROGRESS_AFTER_DOWNLOAD = 70
_PROGRESS_AFTER_ALIGN = 85
_PROGRESS_AFTER_COMPARE = 95
_PROGRESS_AFTER_REPORT = 99


class Orchestrator:
    """Runs the full download/align/compare/report pipeline."""

    def __init__(
        self,
        output_dir: str,
        feedback: Optional[QgsProcessingFeedback] = None,
    ) -> None:
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.feedback = feedback

    # ------------------------------------------------------- cancellation
    def _check_cancelled(self) -> None:
        """Raise :class:`OrchestratorCancelled` if the user pressed Cancel."""
        if self.feedback is not None and self.feedback.isCanceled():
            raise OrchestratorCancelled("Run cancelled by user.")

    def _set_progress(self, percent: float) -> None:
        if self.feedback is not None:
            self.feedback.setProgress(max(0, min(100, percent)))

    def _push_info(self, msg: str) -> None:
        if self.feedback is not None:
            self.feedback.pushInfo(msg)

    # ---------------------------------------------------------- public API
    def run(
        self,
        sources: List[BaseDEMSource],
        extent: ExtentInfo,
        resolution_m: float,
        resampling: str,
        comparison_mode: str,
        reference_id: Optional[str],
    ) -> Tuple[List[QgsRasterLayer], ComparisonResult, str]:
        """Run the full pipeline and return (aligned_layers, stats, report_path).

        :raises OrchestratorError: when no source can serve the extent.
        """
        if not sources:
            raise OrchestratorError("No sources selected.")
        common_extent = to_common_grid(extent)

        # 1) Filter available sources for this extent.
        usable = []
        for src in sources:
            self._check_cancelled()
            if src.is_available(common_extent):
                usable.append(src)
            else:
                if self.feedback is not None:
                    self.feedback.pushWarning(
                        f"{src.name}: {src.unavailable_reason(common_extent)}"
                    )
        if len(usable) < 2:
            raise OrchestratorError(
                "Fewer than two DEM sources are available for this extent. "
                "Nothing to compare."
            )
        self._set_progress(_PROGRESS_AFTER_AVAILABILITY)

        # 2) Download per-source rasters.
        downloaded: List[Tuple[BaseDEMSource, str]] = []
        download_span = _PROGRESS_AFTER_DOWNLOAD - _PROGRESS_AFTER_AVAILABILITY
        step = download_span / max(1, len(usable))
        for i, src in enumerate(usable):
            self._check_cancelled()
            raw_dir = os.path.join(self.output_dir, "raw", src.id)
            os.makedirs(raw_dir, exist_ok=True)
            raw_path = os.path.join(raw_dir, f"{src.id}.tif")
            self._push_info(f"Downloading {src.name}...")
            try:
                src.download(common_extent, raw_path, feedback=self.feedback)
            except Exception as exc:
                if self.feedback is not None:
                    self.feedback.reportError(f"{src.name}: download failed: {exc}")
                continue
            downloaded.append((src, raw_path))
            self._set_progress(_PROGRESS_AFTER_AVAILABILITY + (i + 1) * step)

        if len(downloaded) < 2:
            raise OrchestratorError(
                "Not enough DEMs could be downloaded. See the feedback for details."
            )
        self._set_progress(_PROGRESS_AFTER_DOWNLOAD)

        # 3) Align.
        aligned_dir = os.path.join(self.output_dir, "aligned")
        os.makedirs(aligned_dir, exist_ok=True)
        aligner = make_aligner(aligned_dir, resolution_m=resolution_m, resampling=resampling)
        raster_specs: List[RasterSpec] = [
            RasterSpec(label=src.name, path=path, output_path=os.path.join(
                aligned_dir, f"{src.id}_aligned.tif"))
            for src, path in downloaded
        ]
        grid = aligner.compute_grid(raster_specs)
        align_span = _PROGRESS_AFTER_ALIGN - _PROGRESS_AFTER_DOWNLOAD
        align_step = align_span / max(1, len(raster_specs))
        for i, spec in enumerate(raster_specs):
            self._check_cancelled()
            aligner.align([spec], grid)
            self._set_progress(_PROGRESS_AFTER_DOWNLOAD + (i + 1) * align_step)

        aligned_layers: List[QgsRasterLayer] = []
        for spec in raster_specs:
            layer = QgsRasterLayer(spec.output_path, os.path.basename(spec.output_path))
            aligned_layers.append(layer)

        # 4) Compare.
        diffs_dir = os.path.join(self.output_dir, "diffs")
        reference_label = None
        if comparison_mode == "reference" and reference_id is not None:
            for src, _ in downloaded:
                if src.id == reference_id:
                    reference_label = src.name
                    break
        comparator = Comparator(diffs_dir, reference=reference_label)
        comparator.feedback = self.feedback
        rasters_for_compare = [
            (spec.label, spec.output_path) for spec in raster_specs
        ]
        result = comparator.compare(rasters_for_compare)
        self._set_progress(_PROGRESS_AFTER_COMPARE)

        # 5) Report.
        report_path = os.path.join(self.output_dir, "report.html")
        params = {
            "CRS": COMMON_CRS.authid(),
            "Resolution (m)": resolution_m,
            "Resampling": resampling,
            "Comparison mode": comparison_mode,
            "Reference DEM": reference_label or "(none)",
            "Extent (WGS84)": (
                f"{common_extent.rectangle.xMinimum():.4f}, "
                f"{common_extent.rectangle.yMinimum():.4f} – "
                f"{common_extent.rectangle.xMaximum():.4f}, "
                f"{common_extent.rectangle.yMaximum():.4f}"
            ),
            "Selected sources": ", ".join(s.name for s in usable),
        }
        ReportGenerator(report_path).generate(params, result.pairs, reference_label)
        self._set_progress(_PROGRESS_AFTER_REPORT)

        return aligned_layers, result, report_path

    @staticmethod
    def diff_layers(result: ComparisonResult) -> List[QgsRasterLayer]:
        """Build styled raster layers for every diff raster on disk.

        Each layer gets a diverging blue→red colour ramp symmetric around
        zero, as required by SPEC 3.4. Styling is imported lazily so this
        module still imports without QtGui.
        """
        from .styling import apply_diff_renderer

        layers: List[QgsRasterLayer] = []
        for p in result.pairs:
            layer = QgsRasterLayer(p.diff_raster, os.path.basename(p.diff_raster))
            if layer.isValid():
                apply_diff_renderer(layer, p.diff_min, p.diff_max)
                layers.append(layer)
        return layers