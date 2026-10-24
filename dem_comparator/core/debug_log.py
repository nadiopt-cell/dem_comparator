"""Отладочный логгер — пишет в QGIS Log Messages (View → Panels → Log Messages).

Использование::

    from ..core.debug_log import log, log_error

    log("Старт загрузки")
    log(f"Скачано {n} тайлов", "sources")
    log_error(f"Ошибка: {exc}")
"""
from __future__ import annotations

import inspect
import os
import traceback
from typing import Optional

from qgis.core import QgsMessageLog

TAG = "DEM Comparator"


def log(message: str, tag: str = TAG) -> None:
    """Отправить информационное сообщение в QGIS Log Messages."""
    caller = _caller_info()
    QgsMessageLog.logMessage(f"[{caller}] {message}", tag, level=0)


def log_warn(message: str, tag: str = TAG) -> None:
    """Отправить предупреждение в QGIS Log Messages."""
    caller = _caller_info()
    QgsMessageLog.logMessage(f"[{caller}] {message}", tag, level=1)


def log_error(message: str, exc: Optional[BaseException] = None, tag: str = TAG) -> None:
    """Отправить сообщение об ошибке, опционально с traceback."""
    caller = _caller_info()
    if exc is not None:
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        QgsMessageLog.logMessage(f"[{caller}] {message}\n{tb}", tag, level=2)
    else:
        QgsMessageLog.logMessage(f"[{caller}] {message}", tag, level=2)


def log_variable(name: str, value, tag: str = TAG) -> None:
    """Зафиксировать значение переменной для отладки."""
    caller = _caller_info()
    QgsMessageLog.logMessage(f"[{caller}] {name} = {value!r}", tag, level=0)


def _caller_info() -> str:
    """Вернуть имя файла и номер строки вызвавшего кода."""
    frame = inspect.currentframe()
    # Поднимаемся на 2 фрейма вверх: _caller_info → log → вызывающий код
    try:
        f = frame.f_back.f_back  # type: ignore[union-attr]
        basename = os.path.basename(f.f_code.co_filename)  # type: ignore[union-attr]
        lineno = f.f_lineno  # type: ignore[union-attr]
        return f"{basename}:{lineno}"
    except Exception:
        return "???"
    finally:
        del frame


__all__ = ["log", "log_warn", "log_error", "log_variable"]
