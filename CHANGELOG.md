# Changelog

All notable changes to the **DEM Comparator** QGIS plugin are documented
here. Format follows [Keep a Changelog](https://keepachangelog.com/);
versioning follows [SemVer](https://semver.org/).

## [0.3.1] — 2026-10-24

### Added
- **Local DEM files as comparison inputs** (issue
  [#4](https://github.com/nadiopt-cell/dem_comparator/issues/4)): a new
  "Local DEM files" panel in the dialog accepts one or more rasters
  (GeoTIFF, …) alongside the downloaded sources. Local files are clipped
  to the selected extent, reprojected to EPSG:4326 and enter the
  pipeline exactly like downloaded DEMs, so a 1 m lidar DTM can be
  compared against Copernicus GLO-30 in a single run. Local files are
  also available as reference-DEM candidates, and their paths persist
  between QGIS sessions.
- **Russian UI localization** (issue
  [#7](https://github.com/nadiopt-cell/dem_comparator/issues/7)): when
  the QGIS locale is Russian, the dialog, menu entry, message-bar and
  warning texts are shown in Russian; English remains the fallback for
  any other locale.
- **Repository infrastructure** (issue
  [#9](https://github.com/nadiopt-cell/dem_comparator/issues/9)):
  - GitHub Actions CI: ruff lint, the plain-pytest suite, and the full
    test suite inside the official `qgis/qgis` docker image (un-skips
    the GDAL/QGIS-dependent tests);
  - automatic release packaging: pushing a `vX.Y.Z` tag builds the
    plugin ZIP with [qgis-plugin-ci](https://github.com/opengisch/qgis-plugin-ci)
    and attaches it to the GitHub release;
  - `pre-commit` config (ruff, bandit, detect-secrets) and a
    `scripts/docker_test.sh` helper that mirrors the CI test job
    locally.

### Changed
- Source download contract: `BaseDEMSource.download()` now returns the
  path downstream stages must use (local sources reproject in this step;
  Planetary Computer sources keep writing to the requested path).

## [0.3.0] — 2026-10-24

### Added
- **Robust accuracy metrics** (issue [#2](https://github.com/nadiopt-cell/dem_comparator/issues/2)):
  per-pair **median**, **NMAD** (normalised median absolute deviation,
  Höhle & Höhle 2009) and **LE90/LE95** (90th/95th percentile of the
  absolute difference) are now computed next to RMSE and shown as new
  columns in the HTML report. Robust metrics are resistant to the
  outliers that inflate RMSE, matching how FABDEM/Copernicus GLO-30 are
  validated in the literature.
- **Difference histograms + CSV export** (issue
  [#3](https://github.com/nadiopt-cell/dem_comparator/issues/3)): every
  pair's difference distribution is embedded in the HTML report as an
  inline SVG (50 bins, blue/red diverging colours, zero line), and the
  full statistics table is also written as a machine-readable
  `stats.csv` next to the report.
- **Tile cache** (issue [#5](https://github.com/nadiopt-cell/dem_comparator/issues/5)):
  Planetary Computer tiles are materialised once per source under the
  QGIS profile cache and reused by later runs — repeat runs over the
  same area skip the network entirely, and long warps are no longer
  exposed to SAS-token expiry mid-run. Disable with `use_cache=False`
  (per-source, in code) to restore pure streaming.
- **Vertical datum warnings** (issue
  [#6](https://github.com/nadiopt-cell/dem_comparator/issues/6)): each
  source now declares its vertical datum (FABDEM/GLO-30 → EGM2008;
  SRTM/NASADEM/AW3D30 → EGM96). Mixing the two families pushes a
  warning to the QGIS log and adds a "Vertical datum" line to the
  report parameters.
- **Automatic retries** (issue [#8](https://github.com/nadiopt-cell/dem_comparator/issues/8)):
  all Planetary Computer requests and tile downloads retry transient
  failures (HTTP 429/5xx, network errors) with exponential backoff
  (4 attempts, 1→2→4 s). Permanent errors (404/403) fail fast.

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
- Cancellation is now honoured *inside* the download stage: the tile
  loop checks the cancel flag before every tile, so cancelling during a
  multi-tile download stops promptly instead of after the whole source.

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
