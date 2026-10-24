"""Lightweight runtime localization (RU) — issue #7.

The canonical Qt toolchain (``pylupdate`` + ``lrelease`` → ``.ts``/``.qm``)
is not available in this project's build environment, so instead of
compiled translations we ship a small runtime dictionary:

* English strings live in ``ui/main_dialog.ui`` and in the source code —
  they are the single source of truth and the universal fallback.
* When the QGIS locale is Russian (``Settings → Options → Locale``, the
  ``locale/userLocale`` QSettings key), :func:`tr` substitutes the
  Russian text and :func:`apply_translations` rewrites the static widget
  texts of the dialog right after ``setupUi()``.

Nothing here depends on Qt classes at import time, so the module is
trivially unit-testable outside QGIS.
"""
from __future__ import annotations

from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Locale detection
# ---------------------------------------------------------------------------

_locale_override: Optional[str] = None


def set_locale_override(code: Optional[str]) -> None:
    """Force a locale code (``"ru"``, ``"en"``, …); ``None`` = auto-detect.

    Used by unit tests; in QGIS the locale comes from QSettings.
    """
    global _locale_override  # noqa: PLW0603
    _locale_override = code


def current_locale() -> str:
    """Best-effort UI locale (e.g. ``"ru_RU"``, ``"en"``)."""
    if _locale_override:
        return _locale_override
    try:
        from qgis.PyQt.QtCore import QSettings

        loc = QSettings().value("locale/userLocale", "", str)
        if loc:
            return str(loc)
    except Exception:
        pass
    try:
        from qgis.PyQt.QtCore import QLocale

        return QLocale.system().name()
    except Exception:
        return "en"


def is_russian() -> bool:
    return current_locale().lower().startswith("ru")


# ---------------------------------------------------------------------------
# Dictionary (English → Russian)
# ---------------------------------------------------------------------------

RU: Dict[str, str] = {
    # -- dialog window -----------------------------------------------------
    "DEM Comparator": "Сравнение ЦМР",
    # -- territory group ----------------------------------------------------
    "Territory": "Территория",
    "Extent source:": "Источник охвата:",
    "Canvas extent": "Охват окна карты",
    "Selected vector layer": "Выбранный векторный слой",
    "Drawn on map": "Нарисованный на карте",
    "Manual": "Вручную",
    "Draw on map": "Нарисовать на карте",
    "No extent selected.": "Охват не выбран.",
    "Extent [{crs}]: {x1}, {y1} – {x2}, {y2}":
        "Охват [{crs}]: {x1}, {y1} – {x2}, {y2}",
    "X min:": "X мин:",
    "X max:": "X макс:",
    "Y min:": "Y мин:",
    "Y max:": "Y макс:",
    # -- sources group -------------------------------------------------------
    "DEM sources": "Источники ЦМР",
    "FABDEM (30 m, DTM)": "FABDEM (30 м, DTM)",
    "Copernicus GLO-30 (30 m, DSM)": "Copernicus GLO-30 (30 м, DSM)",
    "NASADEM (30 m, DSM)": "NASADEM (30 м, DSM)",
    "ALOS AW3D30 (30 m, DSM)": "ALOS AW3D30 (30 м, DSM)",
    "SRTM v3 (30 m, DSM)": "SRTM v3 (30 м, DSM)",
    # -- local files group (issue #4) ----------------------------------------
    "Local DEM files": "Локальные файлы ЦМР",
    "Add files…": "Добавить файлы…",
    "Remove selected": "Убрать выбранные",
    "Local files are clipped to the selected extent (reprojected to "
    "EPSG:4326) and compared together with the sources above.":
        "Локальные файлы обрезаются по выбранному охвату (с перепроецированием "
        "в EPSG:4326) и сравниваются вместе с источниками, отмеченными выше.",
    "Select DEM rasters": "Выберите растры ЦМР",
    "GeoTIFF rasters (*.tif *.tiff *.gtiff *.TIF *.TIFF);;All files (*)":
        "Растры GeoTIFF (*.tif *.tiff *.gtiff *.TIF *.TIFF);;Все файлы (*)",
    # -- parameters group ------------------------------------------------------
    "Processing parameters": "Параметры обработки",
    "Resolution:": "Разрешение:",
    "10 m": "10 м",
    "30 m": "30 м",
    "90 m": "90 м",
    "Resampling:": "Ресемплинг:",
    "bilinear": "билинейный",
    "cubic": "бикубический",
    "nearest": "ближайший сосед",
    "Comparison mode:": "Режим сравнения:",
    "All pairs": "Все пары",
    "Reference DEM": "Опорная ЦМР",
    "Reference:": "Опора:",
    # -- output / buttons -------------------------------------------------------
    "Output": "Вывод",
    "Output directory": "Каталог вывода",
    "Choose…": "Выбрать…",
    "Download and compare": "Скачать и сравнить",
    "Cancel": "Отмена",
    "Close": "Закрыть",
    # -- plugin.py user-facing messages -------------------------------------------
    "Open DEM Comparator": "Открыть DEM Comparator",
    "Compare several global DEMs on the same area":
        "Сравнение нескольких глобальных ЦМР на одной территории",
    "DEM Comparator Results": "Результаты DEM Comparator",
    "Select at least one DEM source.": "Выберите хотя бы один источник ЦМР.",
    "No extent available.": "Охват не задан.",
    "Choose an output directory.": "Укажите каталог вывода.",
    "Invalid extent: {exc}": "Некорректный охват: {exc}",
    "File not found: {path}": "Файл не найден: {path}",
    "Local file:": "Локальный файл:",
    "DEM Comparator: download + align + compare":
        "Сравнение ЦМР: загрузка + выравнивание + сравнение",
    "Cancellation requested…": "Запрошена отмена…",
    "Run cancelled.": "Выполнение отменено.",
    "Run failed: {exc}": "Ошибка выполнения: {exc}",
    "Done. {added} layers added. Report: {path}":
        "Готово. Добавлено слоёв: {added}. Отчёт: {path}",
}


def tr(text: str) -> str:
    """Translate ``text`` into the UI locale; English is the fallback."""
    if not is_russian():
        return text
    return RU.get(text, text)


# ---------------------------------------------------------------------------
# Dialog-wide application
# ---------------------------------------------------------------------------

def apply_translations(dialog) -> None:
    """Rewrite static widget texts of ``dialog`` in the current locale.

    Duck-typed on purpose: it walks every child widget and translates
    titles, texts and combo items, so it works with real Qt widgets and
    degrades silently in stub environments (tests without QGIS).
    """
    try:
        if hasattr(dialog, "windowTitle") and hasattr(dialog, "setWindowTitle"):
            dialog.setWindowTitle(tr(dialog.windowTitle()))

        children: List[object] = []
        try:
            children = list(dialog.findChildren())
        except TypeError:
            children = []
        except Exception:
            children = []

        for widget in children:
            # QGroupBox-style widgets: title()/setTitle(). Guarded with a
            # str check so that objects that merely *have* a title()
            # returning something else are not mistaken for group boxes.
            title_getter = getattr(widget, "title", None)
            if callable(title_getter) and hasattr(widget, "setTitle"):
                try:
                    current = title_getter()
                except Exception:
                    current = None
                if isinstance(current, str):
                    widget.setTitle(tr(current))
            # QLabel / QCheckBox / button-style widgets: text()/setText().
            text_getter = getattr(widget, "text", None)
            if callable(text_getter) and hasattr(widget, "setText"):
                try:
                    current = text_getter()
                except Exception:
                    current = None
                if isinstance(current, str):
                    widget.setText(tr(current))
            # Combobox items.
            if (
                hasattr(widget, "count")
                and hasattr(widget, "itemText")
                and hasattr(widget, "setItemText")
            ):
                try:
                    for i in range(widget.count()):
                        widget.setItemText(i, tr(widget.itemText(i)))
                except Exception:
                    pass
    except Exception:
        # Translation must never break the dialog.
        pass


__all__ = ["RU", "apply_translations", "current_locale", "is_russian", "set_locale_override", "tr"]
