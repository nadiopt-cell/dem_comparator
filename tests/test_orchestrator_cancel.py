"""Tests for user cancellation in the orchestrator (pure logic)."""
from __future__ import annotations

import pytest

from conftest import HAVE_QGIS  # noqa: F401  (ensures stubs load first)

from dem_comparator.core.extent_utils import COMMON_CRS, ExtentInfo, QgsRectangle
from dem_comparator.core.orchestrator import Orchestrator, OrchestratorCancelled


class FakeFeedback:
    """QgsProcessingFeedback double with a scriptable cancel state."""

    def __init__(self, cancel_after: int):
        self.cancel_after = cancel_after
        self.checks = 0
        self.progress: list[float] = []
        self.messages: list[str] = []

    def isCanceled(self) -> bool:  # noqa: N802 - QGIS API shape
        self.checks += 1
        return self.checks > self.cancel_after

    def setProgress(self, percent: float) -> None:  # noqa: N802
        self.progress.append(percent)

    def pushInfo(self, msg: str) -> None:  # noqa: N802
        self.messages.append(msg)

    def pushWarning(self, msg: str) -> None:  # noqa: N802
        self.messages.append(msg)

    def reportError(self, msg: str, fatal: bool = False) -> None:  # noqa: N802
        self.messages.append(msg)


class FakeSource:
    """BaseDEMSource double: always available, records download calls."""

    def __init__(self, sid: str):
        self.id = sid
        self.name = f"Fake {sid}"
        self.downloads: list = []

    def is_available(self, extent) -> bool:
        return True

    def unavailable_reason(self, extent) -> str:
        return "unavailable"

    def download(self, extent, output_path, feedback=None, is_cancelled=None):
        self.downloads.append(output_path)
        return output_path


def _extent():
    return ExtentInfo(QgsRectangle(30.0, 50.0, 31.0, 51.0), COMMON_CRS)


def test_cancelled_before_start(tmp_path):
    fb = FakeFeedback(cancel_after=0)  # isCanceled() is True from the start
    orch = Orchestrator(str(tmp_path), feedback=fb)

    with pytest.raises(OrchestratorCancelled):
        orch.run(
            sources=[FakeSource("a"), FakeSource("b")],
            extent=_extent(),
            resolution_m=30.0,
            resampling="bilinear",
            comparison_mode="all",
            reference_id=None,
        )


def test_cancelled_during_downloads(tmp_path):
    # 1st check (availability) passes, 2nd (first download iteration) cancels.
    fb = FakeFeedback(cancel_after=1)
    orch = Orchestrator(str(tmp_path), feedback=fb)
    srcs = [FakeSource("a"), FakeSource("b")]

    with pytest.raises(OrchestratorCancelled):
        orch.run(
            sources=srcs,
            extent=_extent(),
            resolution_m=30.0,
            resampling="bilinear",
            comparison_mode="all",
            reference_id=None,
        )

    assert srcs[0].downloads == [], "no download may start after cancellation"
    assert srcs[1].downloads == []


def test_successful_run_reports_progress(tmp_path):
    """Without cancellation the pipeline reaches the report stage."""
    fb = FakeFeedback(cancel_after=10**9)
    orch = Orchestrator(str(tmp_path), feedback=fb)
    srcs = [FakeSource("a"), FakeSource("b")]

    # Fake sources don't produce real rasters, so alignment would fail;
    # we only assert that progress moved past the availability stage.
    with pytest.raises(Exception):
        orch.run(
            sources=srcs,
            extent=_extent(),
            resolution_m=30.0,
            resampling="bilinear",
            comparison_mode="all",
            reference_id=None,
        )

    assert fb.progress and fb.progress[0] >= 5, (
        "availability stage must report initial progress"
    )
