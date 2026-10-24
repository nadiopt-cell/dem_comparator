# DEM Comparator — QGIS Plugin

[![QGIS](https://img.shields.io/badge/QGIS-3.34%2B-589632)](https://qgis.org)
[![CI](https://github.com/nadiopt-cell/dem_comparator/actions/workflows/ci.yml/badge.svg)](https://github.com/nadiopt-cell/dem_comparator/actions/workflows/ci.yml)
[![License: GPL v2+](https://img.shields.io/badge/License-GPLv2%2B-blue.svg)](LICENSE)

**DEM Comparator** downloads several global DEMs for the same area, aligns them to a common grid, and compares them pairwise with statistics and an HTML report — so you can pick the elevation source that best fits your task. You can also bring your **own local DEM files** (lidar DTM, UAV photogrammetry…) into the same comparison.

## Features

- **5 global DEM sources**: FABDEM, Copernicus GLO-30, NASADEM, ALOS AW3D30, SRTM v3
- **Your own DEM files**: add local rasters (GeoTIFF, …) in the *Local DEM files* panel — they are clipped to the study area, reprojected and compared together with the downloaded sources (e.g. a 1 m lidar DTM vs GLO-30)
- **Russian UI**: the dialog and messages follow the QGIS locale (English is the fallback)
- All sources are fetched via **Microsoft Planetary Computer** (STAC + SAS) — **no API keys required**
- Define the study area by: current map extent, vector layer extent, drawn rectangle, or manual coordinates
- All rasters are automatically aligned to one grid (EPSG:4326; selectable resolution 10 / 30 / 90 m, converted to degrees latitude-aware so the ground sampling matches the requested metres)
- Pairwise comparison in two modes: all pairs, or against a chosen reference DEM
- Per-pair outputs: difference raster + statistics (Mean Bias, MAE, RMSE, Std. Dev., Median, NMAD, LE90/LE95, Min/Max difference, valid pixel count)
- **Difference histograms** (inline SVG) and a machine-readable **stats.csv** in every report
- **Tile cache**: PC tiles are stored once per source in the QGIS profile and reused by later runs (repeat runs over the same area are near-instant and immune to SAS-token expiry)
- **Automatic retries** with exponential backoff for transient Planetary Computer errors (HTTP 429/5xx, network hiccups)
- **Vertical datum awareness**: mixing EGM96-referenced (SRTM/NASADEM/AW3D30) with EGM2008-referenced (FABDEM/GLO-30) sources raises a warning in the log and the report
- Difference rasters come **pre-styled** with a diverging blue→red colour ramp (blue = lower, red = higher)
- Honest per-source **coverage checks** (latitude bounds + STAC probe) with clear skip reasons
- Runs can be **cancelled** at every stage; dialog settings **persist** between QGIS sessions
- Results are added to the project as layers grouped under **"DEM Comparator Results"**
- **HTML report** with run parameters and the full statistics table
- Long-running work runs as a background `QgsTask` — the UI stays responsive and can be cancelled

| Source | Type | Resolution | Vertical datum |
|---|---|---|---|
| FABDEM | DTM | ~30 m | EGM2008 |
| Copernicus GLO-30 | DSM | 30 m | EGM2008 |
| NASADEM | DSM | 30 m | EGM96 |
| ALOS AW3D30 | DSM | 30 m | EGM96 |
| SRTM v3 | DSM | 30 m | EGM96 |

## Requirements

- QGIS **3.34 or newer**
- Internet connection
- No external Python dependencies — only the QGIS API, GDAL and NumPy bundled with QGIS

## Installation

### From ZIP (recommended)

1. Download the latest `dem_comparator-x.y.z.zip` from [Releases](https://github.com/nadiopt-cell/dem_comparator/releases).
2. In QGIS: *Plugins → Manage and Install Plugins → Install from ZIP…*
3. Enable **DEM Comparator** in the plugin list.

### Manual

Copy the `dem_comparator` folder into your QGIS profile plugins directory and restart QGIS:

- Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins`
- Linux/macOS: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins`

## Usage

1. Click the **DEM Comparator** toolbar button to open the dialog.
2. Set the study area (map view, layer extent, drawn rectangle, or manual coordinates).
3. Tick the DEM sources to compare — and/or add your own rasters under *Local DEM files*.
4. Choose output resolution and comparison mode (all pairs or reference DEM).
5. Press **Run** — download, alignment and comparison run in the background.
6. When finished, aligned DEMs, difference rasters and an HTML report are added to your project.

## Documentation

- [Full documentation (English)](DEM_Comparator_Documentation_EN.pdf)
- [Полная документация (русский)](DEM_Comparator_Documentation.pdf)

## Changelog

See [CHANGELOG.md](CHANGELOG.md). Latest: **v0.3.1** — local DEM file inputs, Russian UI localization, CI infrastructure (ruff + QGIS docker tests + automatic release ZIPs).

### Development

```bash
# Lint
python -m pip install ruff && python -m ruff check .

# Tests (pure logic; GDAL/QGIS tests auto-skip)
python3 -m pytest tests/

# Full tests inside the official QGIS image (as CI does)
scripts/docker_test.sh

# Release: push a tag — CI builds the ZIP with qgis-plugin-ci and
# attaches it to the GitHub release automatically.
```

### Running the tests (optional)

```bash
python3 -m pytest tests/
```

Pure-logic tests run with any Python 3.10+ that has NumPy and pytest.
Tests touching GDAL/QGIS (comparator, aligner, styling) automatically
run when invoked with QGIS's Python interpreter and skip otherwise.

## License

Licensed under the **GNU General Public License v2.0 or later** — see [LICENSE](LICENSE).

---

# DEM Comparator — плагин для QGIS (русский)

**DEM Comparator** скачивает несколько глобальных ЦМР на одну и ту же территорию, выравнивает их на единую сетку и попарно сравнивает со статистикой и HTML-отчётом — чтобы выбрать наиболее подходящий источник высот для вашей задачи.

## Возможности

- **5 глобальных источников DEM**: FABDEM, Copernicus GLO-30, NASADEM, ALOS AW3D30, SRTM v3
- **Свои файлы DEM**: добавьте локальные растры (GeoTIFF, …) в панели *Local DEM files* — они обрезаются по территории, перепроецируются и сравниваются вместе со скачанными источниками (например, лидар DTM 1 м против GLO-30)
- **Русский интерфейс**: диалог и сообщения следуют языку QGIS (английский — резервный)
- Все источники загружаются через **Microsoft Planetary Computer** (STAC + SAS) — **ключи API не нужны**
- Задание территории: экстент карты, экстент векторного слоя, нарисованный прямоугольник или ручной ввод координат
- Все растры автоматически приводятся к единой сетке (EPSG:4326; разрешение 10 / 30 / 90 м с учётом широты — наземный шаг соответствует запрошенным метрам)
- Два режима сравнения: все пары или относительно выбранного эталонного DEM
- Для каждой пары: растр разницы и статистика (Mean Bias, MAE, RMSE, Std. Dev., Median, NMAD, LE90/LE95, Min/Max разницы, число валидных пикселей)
- **Гистограммы разниц** (встроенный SVG) и машиночитаемый **stats.csv** в каждом отчёте
- **Кэш тайлов**: тайлы PC сохраняются один раз в профиль QGIS и переиспользуются (повторные прогоны по той же площади — почти мгновенные и не зависят от срока жизни SAS-токена)
- **Автоматические повторы** с экспоненциальной задержкой при временных ошибках Planetary Computer (HTTP 429/5xx, сетевые сбои)
- **Учёт вертикальных датумов**: смешение EGM96 (SRTM/NASADEM/AW3D30) и EGM2008 (FABDEM/GLO-30) даёт предупреждение в журнале и отчёте
- Растры разниц сразу **окрашены** в дивергентную шкалу синий→красный (синий = отрицательная разница, красный = положительная)
- Честная **проверка покрытия** для каждого источника (широтные границы + STAC-проба) с понятными причинами пропуска
- Запуск можно **отменить** на любом этапе; настройки диалога **сохраняются** между сессиями QGIS
- Результаты добавляются в проект группой слоёв **«DEM Comparator Results»**
- **HTML-отчёт** с параметрами запуска и полной таблицей статистики
- Долгие операции выполняются в фоне (`QgsTask`) — интерфейс не зависает, есть отмена

## Требования

- QGIS **3.34 или новее**
- Доступ в интернет
- Внешние Python-зависимости не нужны — только QGIS API, GDAL и NumPy из поставки QGIS

## Установка

### Из ZIP-архива (рекомендуется)

1. Скачайте актуальный `dem_comparator-x.y.z.zip` со страницы [Releases](https://github.com/nadiopt-cell/dem_comparator/releases).
2. В QGIS: *Модули → Управление модулями → Установить из ZIP…*
3. Включите **DEM Comparator** в списке модулей.

### Вручную

Скопируйте папку `dem_comparator` в каталог плагинов профиля QGIS и перезапустите QGIS:

- Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins`
- Linux/macOS: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins`

## Использование

1. Нажмите кнопку **DEM Comparator** на панели инструментов.
2. Задайте территорию (вид карты, слой, прямоугольник на карте или координаты вручную).
3. Отметьте галочками источники DEM и/или добавьте свои растры в панели *Local DEM files*.
4. Выберите разрешение и режим сравнения (все пары или эталонный DEM).
5. Нажмите **Run** — загрузка, выравнивание и сравнение выполнятся в фоне.
6. По завершении в проект будут добавлены выровненные DEM, растры разниц и HTML-отчёт.

## Журнал изменений

См. [CHANGELOG.md](CHANGELOG.md). Актуально: **v0.3.1** — локальные файлы DEM как вход, русская локализация интерфейса, CI-инфраструктура (ruff + тесты в docker QGIS + автоматические ZIP релизов).

### Разработка

```bash
# Линт
python -m pip install ruff && python -m ruff check .

# Тесты (чистая логика; GDAL/QGIS-тесты пропускаются сами)
python3 -m pytest tests/

# Полные тесты в официальном образе QGIS (как в CI)
scripts/docker_test.sh

# Релиз: достаточно запушить тег — CI соберёт ZIP через qgis-plugin-ci
# и приложит его к GitHub-релизу автоматически.
```

### Запуск тестов (необязательно)

```bash
python3 -m pytest tests/
```

Тесты чистой логики выполняются на любом Python 3.10+ с NumPy и pytest.
Тесты, использующие GDAL/QGIS (сравнение, выравнивание, стили), выполняются
под интерпретатором Python из состава QGIS и в остальном окружении
аккуратно пропускаются.

## Лицензия

**GNU General Public License v2.0 или новее** — см. [LICENSE](LICENSE).
