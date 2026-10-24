# Changelog

All notable changes to the **DEM Comparator** QGIS plugin are documented
here. Format follows [Keep a Changelog](https://keepachangelog.com/);
versioning follows [SemVer](https://semver.org/).

## [Unreleased]

### Added
- **Robust accuracy metrics** (issue [#2](https://github.com/nadiopt-cell/dem_comparator/issues/2)):
  per-pair **median**, **NMAD** (normalised median absolute deviation,
  Höhle & Höhle 2009) and **LE90/LE95** (90th/95th percentile of the
  absolute difference) are now computed next to RMSE and shown as new
  columns in the HTML report. Robust metrics are resistant to the
  outliers that inflate RMSE, matching how FABDEM/Copernicus GLO-30 are
  validated in the literature.

### Changed
- **Latitude-aware grid resolution** (issue
  [#1](https://github.com/nadiopt-cell/dem_comparator/issues/1)): the
  requested metric resolution is now converted to degrees using geodesic
  metres-per-degree at the AOI centre latitude (separately for the
  east-west and north-south steps), instead of a single equator factor.
  At 60° N the old code sampled ~56 m east-west when 30 m was requested;
  the ground sampling now matches the requested metres anywhere on the
  globe. The report shows the AOI centre latitude and the actual lon/lat
  grid steps. A full UTM target-CRS option remains future work.

## [0.2.0] — 2026-10-24

### Fixed
- **Difference rasters are now styled.** Each `DIFF_*` layer gets a
  diverging blue→red colour ramp (blue = negative difference, red =
  positive, white = zero) symmetric around zero, as required by SPEC 3.4.
  Previously the layers were added unstyled (grayscale).
- **Cancellation actually works now.** The pipeline checks the user's
  cancel request between every stage: per-source availability, per
  download, per aligned raster, per comparison pair and before the
  report. Cancelling now shows "Run cancelled." in the message bar
  instead of an error, and no further downloads start after the request.
- **Honest coverage checks.** `is_available()` no longer returns a
  blanket `True`. It now (1) checks each source's latitude coverage
  bounds offline (SRTM/NASADEM ±60°, AW3D30 ±82°, FABDEM/GLO-30 global)
  and (2) probes Microsoft Planetary Computer with a STAC search for the
  extent. If PC returns no items, the source is skipped with a clear
  reason instead of failing during download. If PC itself is
  unreachable, the source is assumed available and the download phase
  reports the real error.

### Added
- **Settings persistence (QgsSettings).** Output directory, selected
  sources, resolution, resampling, comparison mode and reference DEM are
  remembered between QGIS sessions.
- **Live progress bar.** The dialog progress bar now follows the
  pipeline (5% → 70% downloads, → 85% alignment, → 95% comparison,
  → report) via `QgsTask.progressChanged`.
- **STAC item cache.** Search results are cached per bbox and reused
  between the availability check and the download, halving STAC
  round-trips.
- **Test suite (pytest).** Coverage for the PC client (token caching,
  signing, pagination), report generation (escaping, NaN handling,
  summaries), availability logic, cancellation, comparator math and
  grid alignment. GDAL/QGIS-dependent tests run inside QGIS's Python and
  skip gracefully elsewhere. Run with `python3 -m pytest tests/`.

### Internal
- New module `core/styling.py` (renderer helpers, kept Qt-import-light).
- `OrchestratorCancelled` exception distinct from `OrchestratorError`.
- `_ProgressForwarder` also forwards warnings, errors and progress.

## [0.1.0] — 2026-08-22

Initial MVP release.

- 5 global DEM sources (FABDEM, Copernicus GLO-30, NASADEM, ALOS
  AW3D30, SRTM v3) via Microsoft Planetary Computer (STAC + SAS, no API
  keys).
- Study area from map extent, layer extent, drawn rectangle or manual
  coordinates.
- Common-grid alignment (EPSG:4326; 10/30/90 m) with selectable
  resampling.
- Pairwise comparison (all pairs or reference DEM) with difference
  rasters and statistics (Mean Bias, MAE, RMSE, Std. Dev., Min/Max,
  valid pixels).
- Results grouped under "DEM Comparator Results" + HTML report.
- Background `QgsTask` execution.
