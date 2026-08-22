"""Background task that runs the orchestrator without blocking the UI."""
from __future__ import annotations

from typing import List, Optional

from qgis.core import (
    QgsApplication,
    QgsProcessingFeedback,
    QgsRasterLayer,
    QgsTask,
)

from .compare import ComparisonResult
from .orchestrator import Orchestrator, OrchestratorError
from ..sources.base import BaseDEMSource


class _ProgressForwarder(QgsProcessingFeedback):
    """Tiny adapter that pipes ``pushInfo`` into a ``QgsTask``."""

    def __init__(self, task: "DemComparatorTask") -> None:
        super().__init__()
        self._task = task

    def pushInfo(self, msg: str) -> None:  # noqa: N802 - QGIS API
        self._task.pushMessage(msg)


class DemComparatorTask(QgsTask):
    """Long-running task: download → align → compare → report."""

    def __init__(
        self,
        description: str,
        output_dir: str,
        sources: List[BaseDEMSource],
        extent,
        resolution_m: float,
        resampling: str,
        comparison_mode: str,
        reference_id: Optional[str],
    ) -> None:
        super().__init__(description, QgsTask.CanCancel)
        self.output_dir = output_dir
        self.sources = sources
        self.extent = extent
        self.resolution_m = resolution_m
        self.resampling = resampling
        self.comparison_mode = comparison_mode
        self.reference_id = reference_id

        self._feedback = _ProgressForwarder(self)
        self.aligned_layers: List[QgsRasterLayer] = []
        self.comparison: Optional[ComparisonResult] = None
        self.report_path: Optional[str] = None
        self.exception: Optional[BaseException] = None

    # ------------------------------------------------------ Qt threading
    def run(self) -> bool:  # noqa: D401 - QGIS task API
        try:
            orch = Orchestrator(self.output_dir, feedback=self._feedback)
            layers, stats, report = orch.run(
                sources=self.sources,
                extent=self.extent,
                resolution_m=self.resolution_m,
                resampling=self.resampling,
                comparison_mode=self.comparison_mode,
                reference_id=self.reference_id,
            )
        except OrchestratorError as exc:
            self.exception = exc
            return False
        except Exception as exc:  # pragma: no cover - defensive
            self.exception = exc
            return False

        self.aligned_layers = layers
        self.comparison = stats
        self.report_path = report
        return True

    def cancel(self) -> None:
        self._feedback.cancel()
        super().cancel()

    def finished(self, result: bool) -> None:
        # Bridge back to the main thread via the taskManagerCompleted signal.
        # The plugin subscribes to it and updates the UI.
        if self.exception is not None:
            self.pushMessage(f"Error: {self.exception}")
        elif not result:
            self.pushMessage("Task did not complete.")
        # Emit a custom message via the application event log for diagnostics.
        try:
            from qgis.core import QgsMessageLog
            if result:
                summary = (
                    f"Run complete. {len(self.aligned_layers)} DEMs aligned, "
                    f"{len(self.comparison.pairs) if self.comparison else 0} pairs, "
                    f"report: {self.report_path}"
                )
                QgsMessageLog.logMessage(summary, "DEM Comparator")
            else:
                QgsMessageLog.logMessage("Run failed", "DEM Comparator")
        except Exception:
            pass


__all__ = ["DemComparatorTask"]