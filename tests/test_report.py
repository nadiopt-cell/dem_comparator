"""Tests for the HTML report generator (pure logic — run anywhere)."""
from __future__ import annotations

import math

from conftest import HAVE_QGIS  # noqa: F401  (ensures stubs load first)

from dem_comparator.core.compare import PairStat
from dem_comparator.core.report import ReportGenerator, _fmt


def _pair(a="FABDEM", b="Copernicus GLO-30", rmse=2.5, bias=1.5,
          vmin=-3.0, vmax=4.0, count=100, median=1.4, nmad=1.1,
          le90=2.2, le95=2.8, hist_counts=None, hist_edges=None):
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
        median=median,
        nmad=nmad,
        le90=le90,
        le95=le95,
        hist_counts=hist_counts,
        hist_edges=hist_edges,
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


def test_report_contains_robust_metric_columns(tmp_path):
    out = tmp_path / "report.html"
    ReportGenerator(str(out)).generate({}, [_pair(nmad=1.05)], None)
    doc = out.read_text(encoding="utf-8")
    # New robust columns are present in the header...
    for header in ("Median (m)", "NMAD (m)", "LE90 (m)", "LE95 (m)"):
        assert header in doc, f"missing column header: {header}"
    # ...and the values are rendered in the row.
    assert "1.050" in doc          # nmad
    assert "2.800" in doc          # le95
    assert "normalised median absolute deviation" in doc  # footnote


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


# -------------------------------------------------------------- histograms
def _hist_pair():
    """A pair whose histogram spans −4…+4 m with a peak near +1."""
    counts = [0, 2, 8, 30, 25, 15, 10, 6, 3, 1]
    edges = [-4, -3.2, -2.4, -1.6, -0.8, 0.0, 0.8, 1.6, 2.4, 3.2, 4.0]
    return _pair(hist_counts=counts, hist_edges=edges)


def test_report_renders_histogram_svg(tmp_path):
    out = tmp_path / "report.html"
    ReportGenerator(str(out)).generate({}, [_hist_pair()], None)
    doc = out.read_text(encoding="utf-8")

    assert "Difference distribution" in doc
    assert "<svg" in doc and "</svg>" in doc
    assert "#2166ac" in doc, "negative bins must use the blue ramp colour"
    assert "#b2182b" in doc, "positive bins must use the red ramp colour"
    assert "stroke-dasharray" in doc, "zero line must be drawn when 0 is in range"
    assert "100 valid pixels" in doc


def test_report_skips_histogram_without_data(tmp_path):
    out = tmp_path / "report.html"
    ReportGenerator(str(out)).generate({}, [_pair()], None)
    doc = out.read_text(encoding="utf-8")
    assert "<svg" not in doc, "pairs without histogram data must not render SVG"
    assert "Difference distribution" not in doc


def test_report_skips_histogram_with_mismatched_edges(tmp_path):
    out = tmp_path / "report.html"
    bad = _pair(hist_counts=[1, 2, 3], hist_edges=[0.0, 1.0])  # need 4 edges
    ReportGenerator(str(out)).generate({}, [bad], None)
    doc = out.read_text(encoding="utf-8")
    assert "<svg" not in doc, "corrupt histogram data must be ignored, not crash"


# --------------------------------------------------------------------- CSV
def test_csv_written_next_to_report(tmp_path):
    csv_path = tmp_path / "stats.csv"
    out = tmp_path / "report.html"
    ReportGenerator(str(out)).generate({}, [_pair()], None, csv_path=str(csv_path))

    assert csv_path.exists()
    lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
    header = lines[0].split(",")
    assert header[:4] == ["DEM A", "DEM B", "valid pixels", "mean bias (m)"]
    assert "NMAD (m)" in header and "LE95 (m)" in header
    row = lines[1].split(",")
    assert row[0] == "FABDEM"
    assert "2.5" in row, "rmse value must appear in the row"

    # The HTML must link the CSV by its bare filename.
    doc = out.read_text(encoding="utf-8")
    assert 'href="stats.csv"' in doc


def test_csv_nan_cells_are_empty(tmp_path):
    import math

    csv_path = tmp_path / "stats.csv"
    nan_pair = PairStat(
        label_a="A", label_b="B", valid_pixels=0,
        mean_bias=math.nan, mae=math.nan, rmse=math.nan,
        std_dev=math.nan, diff_min=math.nan, diff_max=math.nan,
        diff_raster="DIFF_A_minus_B.tif",
    )
    ReportGenerator(str(tmp_path / "report.html")).generate(
        {}, [nan_pair], None, csv_path=str(csv_path)
    )
    content = csv_path.read_text(encoding="utf-8")
    assert "nan" not in content.lower(), "NaN must become an empty cell"
    assert "A,B,0" in content
