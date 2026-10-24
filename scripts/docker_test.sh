#!/usr/bin/env bash
# Run the full test suite inside the official QGIS docker image —
# the same environment the "Tests (QGIS docker)" CI job uses (issue #9).
# This un-skips the GDAL/QGIS-dependent tests.
#
# Usage:  scripts/docker_test.sh [image]     (default: qgis/qgis:3.40 — current LTR)
set -euo pipefail

IMAGE="${1:-qgis/qgis:3.40}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Running tests in $IMAGE"
docker run --rm -v "$ROOT":/io -w /io "$IMAGE" bash -c '
  python3 -m pip install --quiet --break-system-packages pytest
  xvfb-run -a python3 -m pytest tests/ -v
'
