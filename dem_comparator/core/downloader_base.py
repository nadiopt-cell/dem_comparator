"""HTTP/FTP downloader used by all DEM sources.

Centralising the network code here gives every source:

- pluggable progress reporting via ``QgsProcessingFeedback``;
- a single, predictable cache layout (per-source sub-folder);
- cancellation that propagates through every source without per-source code;
- a small, well-tested set of error messages.

The downloader deliberately uses **only stdlib** (``urllib`` + ``shutil``).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import socket
import tempfile
import urllib.error
import urllib.request
from typing import Callable, Optional
from urllib.parse import urlparse

from qgis.core import QgsMessageLog, QgsProcessingFeedback

# Generous default timeout (s). DEM tiles are slow over HTTPS.
DEFAULT_TIMEOUT = 60

# Bytes per progress tick when reporting to the feedback object.
_TICK = 1 << 16  # 64 KiB


class DownloadError(Exception):
    """Raised when a remote resource cannot be fetched."""


class DownloaderBase:
    """Stateless helper. Instances are cheap; create one per source."""

    def __init__(
        self,
        cache_dir: str,
        timeout: int = DEFAULT_TIMEOUT,
        user_agent: str = "QGIS-DEM-Comparator/0.1",
    ) -> None:
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.user_agent = user_agent

    # --------------------------------------------------------------- paths
    def cache_path(self, url: str, suffix: str = ".tif") -> str:
        """Return a deterministic per-URL path inside ``self.cache_dir``."""
        os.makedirs(self.cache_dir, exist_ok=True)
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, digest + suffix)

    # ---------------------------------------------------------- downloading
    def download(
        self,
        url: str,
        output_path: str,
        feedback: Optional[QgsProcessingFeedback] = None,
        use_cache: bool = True,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> str:
        """Download ``url`` to ``output_path`` (or to cache and copy).

        :param url: remote URL.
        :param output_path: where the caller wants the file.
        :param feedback: optional feedback object for progress reporting.
        :param use_cache: when True, the file is cached and reused if present.
        :param is_cancelled: callable returning True to abort the transfer.
        :returns: absolute path of the produced file (``output_path``).
        :raises DownloadError: on network failure or remote HTTP error.
        """
        if use_cache:
            cached = self.cache_path(url)
            if os.path.exists(cached) and os.path.getsize(cached) > 0:
                if output_path != cached:
                    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
                    shutil.copy2(cached, output_path)
                if feedback is not None:
                    feedback.pushInfo(f"[cache] {url}")
                return output_path

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        if use_cache:
            os.makedirs(self.cache_dir, exist_ok=True)

        # Write to a temp file first, then rename/copy atomically.
        tmp_fd, tmp_path = tempfile.mkstemp(prefix="dem_cmp_", suffix=".part")
        os.close(tmp_fd)

        try:
            request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    with open(tmp_path, "wb") as out:
                        total = 0
                        while True:
                            if is_cancelled is not None and is_cancelled():
                                raise DownloadError("Cancelled")
                            chunk = response.read(_TICK)
                            if not chunk:
                                break
                            out.write(chunk)
                            total += len(chunk)
                            if feedback is not None:
                                feedback.pushInfo(f"Downloaded {total} bytes of {url}")
            except (urllib.error.URLError, socket.timeout, ConnectionError) as exc:
                raise DownloadError(f"Network error while fetching {url}: {exc}") from exc

            if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
                raise DownloadError(f"Empty or missing file for {url}")

            if use_cache:
                cached = self.cache_path(url)
                shutil.copy2(tmp_path, cached)

            shutil.copy2(tmp_path, output_path)
            return output_path
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    # ------------------------------------------------------------- helpers
    @staticmethod
    def url_filename(url: str) -> str:
        """Return the last non-empty path segment of ``url``."""
        path = urlparse(url).path
        return os.path.basename(path) or "download.bin"

    @staticmethod
    def log(message: str) -> None:
        """Forward message to QGIS message log under the `DEM Comparator` tag."""
        try:
            from qgis.core import Qgis  # noqa: F401  - only for side-effect import
            QgsMessageLog.logMessage(message, "DEM Comparator")
        except Exception:
            # Outside QGIS (e.g. unit tests) we keep the plugin importable.
            pass
