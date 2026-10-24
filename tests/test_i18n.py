"""Tests for the runtime RU localization layer (issue #7)."""
from __future__ import annotations

from dem_comparator.i18n import (
    RU,
    apply_translations,
    current_locale,
    is_russian,
    set_locale_override,
    tr,
)


def setup_function(_fn) -> None:
    # every test starts from a clean, explicit locale
    set_locale_override(None)


def teardown_function(_fn) -> None:
    set_locale_override(None)


def test_tr_falls_back_to_english():
    set_locale_override("en")
    assert tr("Cancel") == "Cancel"
    assert tr("Not in the dictionary") == "Not in the dictionary"


def test_tr_russian_known_and_unknown():
    set_locale_override("ru")
    assert tr("Cancel") == "Отмена"
    assert tr("Download and compare") == "Скачать и сравнить"
    # unknown strings pass through unchanged (English fallback)
    assert tr("Totally unknown string") == "Totally unknown string"


def test_tr_templates_translate_before_formatting():
    set_locale_override("ru")
    template = tr("Run failed: {exc}")
    assert template == "Ошибка выполнения: {exc}"
    assert template.format(exc=ValueError("x")) == "Ошибка выполнения: x"


def test_locale_case_insensitive():
    set_locale_override("ru_RU")
    assert is_russian() is True
    set_locale_override("RU")
    assert is_russian() is True
    set_locale_override("en_US")
    assert is_russian() is False


def test_current_locale_fallback_without_qt():
    # no override, QSettings is a stub that raises → falls back to "en"
    assert isinstance(current_locale(), str)
    assert current_locale() != ""


def test_ru_dictionary_no_empty_or_duplicate_values():
    # every translation must be a non-empty string and distinct from the key
    # (a key equal to its value means a forgotten translation)
    for key, value in RU.items():
        assert isinstance(value, str) and value.strip(), f"bad value for {key!r}"
        assert value != key, f"translation for {key!r} is identical to the source"


class _FakeWidget:
    """Duck-typed widget double: enough surface for apply_translations."""

    def __init__(self, text=None, title=None, items=None):
        self._text = text
        self._title = title
        self._items = list(items or [])
        self.text_calls = 0

    # label / button / checkbox API
    def text(self):
        self.text_calls += 1
        return self._text

    def setText(self, value):  # noqa: N802
        self._text = value

    # group box API
    def title(self):
        return self._title

    def setTitle(self, value):  # noqa: N802
        self._title = value

    # combobox API
    def count(self):
        return len(self._items)

    def itemText(self, i):  # noqa: N802
        return self._items[i]

    def setItemText(self, i, value):  # noqa: N802
        self._items[i] = value


class _FakeDialog:
    def __init__(self, children):
        self._children = children
        self._title = "DEM Comparator"

    def windowTitle(self):
        return self._title

    def setWindowTitle(self, value):  # noqa: N802
        self._title = value

    def findChildren(self):
        return self._children


def test_apply_translations_rewrites_all_widget_kinds():
    set_locale_override("ru")
    group = _FakeWidget(title="Territory")
    label = _FakeWidget(text="Resolution:")
    button = _FakeWidget(text="Cancel")
    combo = _FakeWidget(items=["10 m", "30 m", "90 m"])
    dialog = _FakeDialog([group, label, button, combo])

    apply_translations(dialog)

    assert dialog._title == "Сравнение ЦМР"
    assert group._title == "Территория"
    assert label._text == "Разрешение:"
    assert button._text == "Отмена"
    assert combo._items == ["10 м", "30 м", "90 м"]


def test_apply_translations_never_raises():
    class _Broken:
        def findChildren(self):
            raise RuntimeError("boom")

    set_locale_override("ru")
    apply_translations(_Broken())      # must not raise
    apply_translations(_FakeDialog([object()]))  # unknown widgets are ignored
