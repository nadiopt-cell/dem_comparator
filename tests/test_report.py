"""Tests for the HTML report generator (pure logic — run anywhere)."""
from __future__ import annotations

import math

from conftest import HAVE_QGIS  # noqa: F401  (ensures stubs load first)

from dem_comparator.core.compare import PairStat
from dem_comparator.core.report import ReportGenerator, _fmt


def _pair(a="FABDEM", b="Copernicus GLO-30", rmse=2.5, bias=1.5,
          vmin=-3.0, vmax=4.0, count=100):
    return PairStat(
        label_a=a,
        label_b=b,
        valid_pixels=count,
        mean_bias=bias,
        mae=2.0,
        rmse=rmse,
        std_dev=1.2,
        diff_min=vmin,
        diff_max=vmax,
        diff_raster=f"DIFF_{a}_minus_{b}.tif",
    )


# --------------------------------------------------------------- generation
def test_report_written_and_contains_table(tmp_path):
    out = tmp_path / "report.html"
    ReportGenerator(str(out)).generate(
        {"CRS": "EPSG:4326", "Resolution (m)": 30.0},
        [_pair(), _pair("NASADEM", "Copernicus GLO-30", rmse=1.1)],
        None,
    )

    doc = out.read_text(encoding="utf-8")
    assert out.exists()
    assert "DEM Comparator" in doc
    assert "RMSE" in doc
    assert "FABDEM" in doc
    assert "NASADEM" in doc
    assert "EPSG:4326" in doc


def test_report_summary_picks_smallest_rmse_all_pairs(tmp_path):
    out = tmp_path / "report.html"
    ReportGenerator(str(out)).generate({}, [_pair(rmse=2.5), _pair("NASADEM", "GLO30", rmse=0.9)], None)
    doc = out.read_text(encoding="utf-8")
    assert "NASADEM − GLO30" in doc
    assert "0.900" in doc


def test_report_summary_reference_mode(tmp_path):
    out = tmp_path / "report.html"
    pairs = [
        _pair("Copernicus GLO-30", "FABDEM", rmse=3.0),
        _pair("Copernicus GLO-30", "SRTM v3", rmse=1.5),
    ]
    ReportGenerator(str(out)).generate({}, pairs, "Copernicus GLO-30")
    doc = out.read_text(encoding="utf-8")
    assert "Reference DEM is" in doc
    assert "SRTM v3" in doc


def test_report_escapes_labels(tmp_path):
    out = tmp_path / "report.html"
    evil = "<script>x</script>"
    ReportGenerator(str(out)).generate({}, [_pair(a=evil)], None)
    doc = out.read_text(encoding="utf-8")
    assert "<script>" not in doc
    assert "&lt;script&gt;" in doc


def test_report_handles_nan_stats(tmp_path):
    out = tmp_path / "report.html"
    nan_pair = PairStat(
        label_a="A", label_b="B", valid_pixels=0,
        mean_bias=math.nan, mae=math.nan, rmse=math.nan,
        std_dev=math.nan, diff_min=math.nan, diff_max=math.nan,
        diff_raster="DIFF_A_minus_B.tif",
    )
    ReportGenerator(str(out)).generate({}, [nan_pair], None)
    doc = out.read_text(encoding="utf-8")
    assert "—" in doc, "NaN values must render as an em dash, not 'nan'"
    assert "nan" not in doc.lower().replace("nasadem", "")


# ----------------------------------------------------------------- _fmt util
def test_fmt():
    assert _fmt(1.23456) == "1.235"
    assert _fmt(123.456) == "123.5"
    assert _fmt(float("nan")) == "—"
    assert _fmt(None) == ""
    assert _fmt("abc") == "abc"
