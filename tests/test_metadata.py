"""Sanity tests tying the visible version to the changelog (pure stdlib)."""
from __future__ import annotations

import configparser
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO_ROOT / "dem_comparator"


def _metadata_version() -> str:
    md = PLUGIN_DIR / "metadata.txt"
    parser = configparser.ConfigParser()
    parser.read(md, encoding="utf-8")
    return parser["general"]["version"]


def _changelog_latest_version() -> str:
    text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"^## \[?(\d+\.\d+\.\d+)\]?", text, flags=re.MULTILINE)
    assert match, "CHANGELOG.md must contain at least one '## [x.y.z]' heading"
    return match.group(1)


def test_metadata_and_changelog_versions_match():
    assert _metadata_version() == _changelog_latest_version()


def test_metadata_has_required_keys():
    parser = configparser.ConfigParser()
    parser.read(PLUGIN_DIR / "metadata.txt", encoding="utf-8")
    general = parser["general"]
    for key in ("name", "version", "qgisMinimumVersion", "author", "description",
                "about", "tracker", "repository", "tags", "icon"):
        assert key in general and general[key].strip(), f"metadata.txt missing '{key}'"


def test_all_source_ids_have_checkboxes():
    """Every registered source must have a mapping in the dialog."""
    from dem_comparator.sources.registry import available_sources

    # Re-import the dialog mapping without instantiating Qt widgets:
    # read the module source for _SOURCE_CHECKBOX keys.
    dialog_src = (PLUGIN_DIR / "ui" / "main_dialog.py").read_text(encoding="utf-8")
    for cls in available_sources():
        assert f'"{cls.id}"' in dialog_src, (
            f"Source id '{cls.id}' is not wired in ui/main_dialog.py"
        )
