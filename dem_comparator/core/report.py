"""HTML report generator.

Produces a single self-contained HTML file with:

- run parameters (extent, sources, resolution, CRS, vertical datums);
- a table of per-pair statistics (RMSE / MAE / bias / std-dev / median /
  NMAD / LE90 / LE95 / min / max);
- inline-SVG histograms of each pair's difference distribution (issue
  #3 — no JavaScript, no external images);
- a short summary line per pair ("X is closer to Y than Z");
- links to the rasters on disk (the rest of the UI opens them).

Optionally (when the orchestrator passes ``csv_path``) the same stats
are written next to it as a machine-readable CSV.

The HTML side depends on the standard library only. The CSS is inline,
very small, and tuned for readability inside QGIS's "open in browser"
dialog.
"""
from __future__ import annotations

import csv
import datetime
import html
import json
import os
from typing import Iterable, List, Mapping, Optional, Sequence

from .compare import PairStat

_CSS = """
body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px; color: #222; }
h1, h2, h3 { color: #2b3d4f; }
table { border-collapse: collapse; margin: 12px 0; width: 100%; }
th, td { border: 1px solid #ddd; padding: 6px 8px; text-align: right; }
th { background: #f3f5f7; }
.label, td.label, th.label { text-align: left; }
tr:nth-child(even) td { background: #fafafa; }
.kv { background: #f8f8f8; padding: 8px 12px; border-radius: 4px; display: inline-block; margin: 2px 4px 2px 0; }
.hint { color: #666; font-size: 12px; margin: 4px 0; }
.hist { margin: 8px 0 20px 0; }
.hist svg { background: #fcfcfd; border: 1px solid #e3e6ea; border-radius: 4px; }
.hist h3 { margin: 10px 0 2px 0; font-size: 14px; }
footer { margin-top: 24px; color: #888; font-size: 12px; }
"""

# Diverging bar colours — the same ramp the diff rasters use (SPEC 3.4):
# blue = negative difference (B higher), red = positive (A higher).
_HIST_NEG_COLOR = "#2166ac"
_HIST_POS_COLOR = "#b2182b"
_HIST_ZERO_COLOR = "#878787"

# Columns of the machine-readable companion CSV (issue #3).
_CSV_COLUMNS = (
    ("label_a", "DEM A"),
    ("label_b", "DEM B"),
    ("valid_pixels", "valid pixels"),
    ("mean_bias", "mean bias (m)"),
    ("mae", "MAE (m)"),
    ("rmse", "RMSE (m)"),
    ("std_dev", "std dev (m)"),
    ("median", "median (m)"),
    ("nmad", "NMAD (m)"),
    ("le90", "LE90 (m)"),
    ("le95", "LE95 (m)"),
    ("diff_min", "min (m)"),
    ("diff_max", "max (m)"),
)


class ReportGenerator:
    """Compose the HTML report and write it to disk."""

    def __init__(self, output_path: str) -> None:
        self.output_path = output_path

    # ------------------------------------------------------------------
    def generate(
        self,
        run_params: Mapping[str, object],
        pairs: Sequence[PairStat],
        reference: str | None = None,
        csv_path: Optional[str] = None,
    ) -> str:
        html_doc = self._render(run_params, pairs, reference, csv_path=csv_path)
        os.makedirs(os.path.dirname(self.output_path) or ".", exist_ok=True)
        with open(self.output_path, "w", encoding="utf-8") as fh:
            fh.write(html_doc)
        if csv_path is not None:
            self.write_csv(pairs, csv_path)
        return self.output_path

    # ------------------------------------------------------------------
    def write_csv(self, pairs: Sequence[PairStat], csv_path: str) -> str:
        """Write the per-pair statistics as a flat CSV (issue #3).

        NaN values become empty cells so spreadsheets treat them as
        missing rather than as text.
        """
        os.makedirs(os.path.dirname(csv_path) or ".", exist_ok=True)
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow([header for _, header in _CSV_COLUMNS])
            for p in pairs:
                writer.writerow([_csv_cell(getattr(p, attr)) for attr, _ in _CSV_COLUMNS])
        return csv_path

    # ------------------------------------------------------------------
    @staticmethod
    def _render(
        run_params: Mapping[str, object],
        pairs: Sequence[PairStat],
        reference: str | None,
        csv_path: Optional[str] = None,
    ) -> str:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        param_html = "".join(
            f'<span class="kv"><b>{html.escape(str(k))}:</b> {html.escape(str(v))}</span>'
            for k, v in run_params.items()
        )

        pair_rows = "".join(ReportGenerator._row(p) for p in pairs)

        summary = ReportGenerator._summary(pairs, reference)
        histogram_section = ReportGenerator._histogram_section(pairs)
        csv_link = ""
        if csv_path:
            name = os.path.basename(csv_path)
            csv_link = (
                f'<p class="hint">Machine-readable statistics: '
                f'<a href="{html.escape(name)}">{html.escape(name)}</a></p>'
            )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>DEM Comparator — Report</title>
  <style>{_CSS}</style>
</head>
<body>
  <h1>DEM Comparator — Report</h1>
  <p>Generated {html.escape(now)}</p>

  <h2>Run parameters</h2>
  <div>{param_html}</div>

  <h2>Pairwise statistics ({len(pairs)} pairs)</h2>
  <p class="hint">NMAD = normalised median absolute deviation (robust);
  LE90/LE95 = 90th/95th percentile of the absolute difference. Robust
  metrics are resistant to outliers that inflate RMSE.</p>
  <table>
    <thead>
      <tr>
        <th class="label">Pair (A − B)</th>
        <th>Valid pixels</th>
        <th>Mean bias (m)</th>
        <th>MAE (m)</th>
        <th>RMSE (m)</th>
        <th>Std dev (m)</th>
        <th>Median (m)</th>
        <th>NMAD (m)</th>
        <th>LE90 (m)</th>
        <th>LE95 (m)</th>
        <th>Min (m)</th>
        <th>Max (m)</th>
      </tr>
    </thead>
    <tbody>{pair_rows}</tbody>
  </table>
  {csv_link}

  <h2>Summary</h2>
  <p>{summary}</p>

  {histogram_section}

  <footer>Generated by DEM Comparator plugin.</footer>
</body>
</html>
"""

    @staticmethod
    def _row(p: PairStat) -> str:
        title = f"{p.label_a} − {p.label_b}"
        cells = "".join(
            f'<td>{html.escape(_fmt(v))}</td>'
            for v in (
                p.valid_pixels,
                p.mean_bias,
                p.mae,
                p.rmse,
                p.std_dev,
                p.median,
                p.nmad,
                p.le90,
                p.le95,
                p.diff_min,
                p.diff_max,
            )
        )
        return f'<tr><td class="label">{html.escape(title)}</td>{cells}</tr>'

    @staticmethod
    def _summary(pairs: Iterable[PairStat], reference: str | None) -> str:
        pairs = list(pairs)
        if not pairs:
            return "No pairs to compare."
        if reference is not None:
            best = min(
                (p for p in pairs if p.label_a == reference),
                key=lambda p: p.rmse,
                default=None,
            )
            if best is None:
                return f"Reference DEM was <b>{html.escape(reference)}</b> but no pairs were computed."
            return (
                f"Reference DEM is <b>{html.escape(reference)}</b>. "
                f"Closest match by RMSE: <b>{html.escape(best.label_b)}</b> "
                f"(RMSE = {_fmt(best.rmse)} m)."
            )
        best = min(pairs, key=lambda p: p.rmse)
        return (
            f"Across all pairs, the smallest RMSE is "
            f"<b>{html.escape(best.label_a)} − {html.escape(best.label_b)}</b> "
            f"(RMSE = {_fmt(best.rmse)} m)."
        )

    # -------------------------------------------------------- histograms
    @staticmethod
    def _histogram_section(pairs: Sequence[PairStat]) -> str:
        """Inline-SVG difference histograms for every pair that has one."""
        blocks: List[str] = []
        for p in pairs:
            svg = ReportGenerator._hist_svg(p)
            if svg is None:
                continue
            title = f"{p.label_a} − {p.label_b}"
            caption = (
                f"median = {_fmt(p.median)} m, NMAD = {_fmt(p.nmad)} m. "
                "Bars left of the dashed zero line are negative "
                "(DEM B higher); blue = negative, red = positive."
            )
            blocks.append(
                f'<div class="hist"><h3>{html.escape(title)}</h3>'
                f"{svg}<p class=\"hint\">{html.escape(caption)}</p></div>"
            )
        if not blocks:
            return ""
        return (
            '<h2>Difference distribution</h2>'
            '<p class="hint">Histogram of the per-pixel difference '
            "(50 bins). A skewed or bimodal distribution means the mean "
            "bias hides structure — look at the robust metrics too.</p>"
            + "".join(blocks)
        )

    @staticmethod
    def _hist_svg(p: PairStat, width: int = 640, height: int = 120) -> Optional[str]:
        """Render one pair's histogram as a small inline SVG.

        Returns ``None`` when the pair carries no histogram data (older
        run or zero valid pixels).
        """
        counts = list(p.hist_counts or [])
        edges = list(p.hist_edges or [])
        if not counts or len(edges) != len(counts) + 1:
            return None

        baseline = height - 20
        max_count = max(counts) or 1
        n = len(counts)
        bar_w = width / n

        bars: List[str] = []
        for i, c in enumerate(counts):
            if c <= 0:
                continue
            centre = 0.5 * (edges[i] + edges[i + 1])
            if centre < 0:
                color = _HIST_NEG_COLOR
            elif centre > 0:
                color = _HIST_POS_COLOR
            else:
                color = _HIST_ZERO_COLOR
            h = max(1.0, (baseline - 4) * c / max_count)
            x = i * bar_w
            y = baseline - h
            bars.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" '
                f'height="{h:.1f}" fill="{color}"/>'
            )

        zero_line = ""
        lo, hi = edges[0], edges[-1]
        if lo <= 0 <= hi and hi > lo:
            x0 = (0.0 - lo) / (hi - lo) * width
            zero_line = (
                f'<line x1="{x0:.1f}" y1="0" x2="{x0:.1f}" y2="{baseline}" '
                'stroke="#444" stroke-width="1" stroke-dasharray="4,3"/>'
            )

        axis = (
            f'<line x1="0" y1="{baseline}" x2="{width}" y2="{baseline}" '
            'stroke="#999" stroke-width="1"/>'
        )
        labels = (
            f'<text x="2" y="{height - 6}" font-size="11" fill="#666">'
            f'{html.escape(_fmt(lo))} m</text>'
            f'<text x="{width - 2}" y="{height - 6}" font-size="11" '
            f'fill="#666" text-anchor="end">{html.escape(_fmt(hi))} m</text>'
            f'<text x="{width / 2}" y="{height - 6}" font-size="11" fill="#999" '
            f'text-anchor="middle">{p.valid_pixels} valid pixels</text>'
        )
        return (
            f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
            f'role="img" xmlns="http://www.w3.org/2000/svg">'
            f'{zero_line}{axis}{"".join(bars)}{labels}</svg>'
        )


def _fmt(value: float) -> str:
    """Format a numeric value for the HTML table."""
    if value is None:
        return ""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    if f != f:  # NaN check
        return "—"
    if abs(f) >= 100:
        return f"{f:.1f}"
    return f"{f:.3f}"


def _csv_cell(value) -> object:
    """Map a stat value onto a CSV cell (NaN → empty string)."""
    if isinstance(value, float) and value != value:  # NaN
        return ""
    return value


def run_params_from_dict(d: Mapping[str, object]) -> dict:
    """Round-trip helper used by unit tests."""
    return json.loads(json.dumps(d, default=str))
