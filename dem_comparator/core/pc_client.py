"""Microsoft Planetary Computer client — STAC + SAS, stdlib only.

Why a dedicated client:

The five DEM sources the plugin supports are all mirrored as STAC
collections on Microsoft Planetary Computer (PC). PC exposes:

* a STAC catalogue at ``https://planetarycomputer.microsoft.com/api/stac/v1``
* a per-collection SAS-token endpoint at
  ``https://planetarycomputer.microsoft.com/api/sas/v1/token/<collection>``
  (returns JSON ``{"token": "...", "msft:expiry": "..."}``).

Token is public, anonymous, valid ~1 hour. We cache it per collection in
memory so multiple calls within a run reuse it. Items are queried by
``bbox``; the catalogue returns Cloud-Optimised GeoTIFF URLs whose
asset path can be fetched with the token appended (``?<token>``).

The client uses **only** the standard library (``urllib`` + ``json``),
so it works inside the QGIS plugin process without extra deps.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

# Endpoint base URLs (current at time of writing — August 2026).
STAC_ROOT = "https://planetarycomputer.microsoft.com/api/stac/v1"
SAS_BASE = "https://planetarycomputer.microsoft.com/api/sas/v1/token"

# Retry policy for transient failures (issue #8): PC throttles bursts and
# occasionally answers 5xx; a short exponential backoff turns those into
# successful downloads instead of a failed run.
RETRY_ATTEMPTS = 4
RETRY_BACKOFF_SECONDS = 1.0
_RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
_CHUNK_BYTES = 1 << 20  # 1 MiB

# Module-level indirection so tests can patch the sleep out.
_sleep = time.sleep


class PCError(Exception):
    """Raised when the PC catalogue or token endpoint fails."""


def _urlopen_with_retry(
    request_factory: Callable[[int], urllib.request.Request],
    *,
    attempts: int = RETRY_ATTEMPTS,
    backoff_seconds: float = RETRY_BACKOFF_SECONDS,
    timeout: int = 60,
    what: str = "PC",
    feedback=None,
):
    """Open a URL with exponential backoff on transient errors.

    ``request_factory(attempt)`` must build a *fresh* request for each
    attempt (a consumed :class:`urllib.request.Request` cannot be resent
    after a body-reading failure).

    Retried: HTTP 429/5xx and network-level :class:`URLError`/``OSError``.
    Other HTTP errors (403/404, …) are raised immediately — retrying them
    cannot help. When all attempts are exhausted a :class:`PCError` is
    raised with the last underlying exception as ``__cause__``.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return urllib.request.urlopen(request_factory(attempt), timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code not in _RETRYABLE_HTTP_CODES:
                raise
            last_exc = exc
        except (urllib.error.URLError, OSError) as exc:
            last_exc = exc
        if attempt < attempts:
            delay = backoff_seconds * (2 ** (attempt - 1))
            if feedback is not None:
                try:
                    feedback.pushInfo(
                        f"{what}: transient error ({last_exc}); "
                        f"retry {attempt + 1}/{attempts} in {delay:.1f}s"
                    )
                except Exception:  # feedback must never break downloads
                    pass
            _sleep(delay)
    raise PCError(f"{what}: giving up after {attempts} attempt(s): {last_exc}") from last_exc


def download_to_file(
    url: str,
    dest_path: str,
    *,
    timeout: int = 300,
    attempts: int = RETRY_ATTEMPTS,
    backoff_seconds: float = RETRY_BACKOFF_SECONDS,
    user_agent: str = "QGIS-DEM-Comparator/0.3 (PC)",
    feedback=None,
) -> str:
    """Stream ``url`` to ``dest_path`` with retry/backoff (issue #5 helper).

    The bytes land in ``dest_path + ".part"`` first and are renamed on
    success, so a cancelled or failed download never leaves a corrupt
    file behind. Returns ``dest_path``.
    """
    def _factory(_attempt: int) -> urllib.request.Request:
        return urllib.request.Request(url, headers={"User-Agent": user_agent})

    tmp_path = dest_path + ".part"
    try:
        with _urlopen_with_retry(
            _factory,
            attempts=attempts,
            backoff_seconds=backoff_seconds,
            timeout=timeout,
            what="PC tile download",
            feedback=feedback,
        ) as resp, open(tmp_path, "wb") as fh:
            while True:
                chunk = resp.read(_CHUNK_BYTES)
                if not chunk:
                    break
                fh.write(chunk)
    except PCError:
        _quiet_remove(tmp_path)
        raise
    except Exception as exc:
        _quiet_remove(tmp_path)
        raise PCError(f"Tile download failed for {url}: {exc}") from exc
    os.replace(tmp_path, dest_path)
    return dest_path


def _quiet_remove(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


@dataclass
class PCItem:
    """A single STAC item returned by the catalogue."""

    item_id: str
    href: str             # asset URL (no token yet)
    asset_key: str        # which asset we picked (e.g. "data" / "elevation")
    signed_href: str      # href with ?<token> appended

    @property
    def out_name(self) -> str:
        """Suggested on-disk filename for this item."""
        return _safe_filename(self.href)


class PlanetaryComputerClient:
    """Stateless-ish PC client (token cache lives on the instance)."""

    def __init__(
        self,
        token_cache_path: Optional[str] = None,
        timeout: int = 60,
        user_agent: str = "QGIS-DEM-Comparator/0.3 (PC)",
        retry_attempts: int = RETRY_ATTEMPTS,
        retry_backoff_seconds: float = RETRY_BACKOFF_SECONDS,
    ) -> None:
        self._token_cache: Dict[str, Tuple[str, float]] = {}
        self._token_cache_path = token_cache_path
        if token_cache_path:
            self._load_token_cache()
        self.timeout = timeout
        self.user_agent = user_agent
        # Retry policy (issue #8); feedback may be attached by the caller so
        # retries show up in the QGIS log.
        self.retry_attempts = retry_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self.feedback = None

    # -------------------------------------------------------------- tokens
    def get_sas_token(self, collection: str) -> str:
        """Return a SAS token for ``collection`` (cached for ~50 minutes)."""
        cached = self._token_cache.get(collection)
        if cached is not None and cached[1] > time.time() + 60:
            return cached[0]
        url = f"{SAS_BASE}/{collection}"
        body = self._http_get_json(url)
        token = body.get("token")
        if not token:
            raise PCError(f"PC SAS endpoint returned no token for {collection}: {body!r}")
        # PC tokens typically live ~60 minutes; refresh a little earlier.
        self._token_cache[collection] = (token, time.time() + 50 * 60)
        self._save_token_cache()
        return token

    # ---------------------------------------------------------- STAC search
    def search_items(
        self,
        collection: str,
        bbox: Tuple[float, float, float, float],
        limit: int = 200,
        extra_query: Optional[Dict[str, object]] = None,
    ) -> List[dict]:
        """Return raw STAC item dicts intersecting ``bbox`` (WGS84)."""
        xmin, ymin, xmax, ymax = bbox
        url = f"{STAC_ROOT}/search"
        body = {
            "collections": [collection],
            "bbox": [xmin, ymin, xmax, ymax],
            "limit": limit,
        }
        if extra_query:
            body["query"] = extra_query
        raw = self._http_post_json(url, body)
        items = raw.get("features", [])
        if not items:
            return []
        # PC uses cursor pagination; follow ``next`` until exhausted.
        next_link = self._next_link(raw)
        while next_link:
            more = self._http_get_json(next_link)
            items.extend(more.get("features", []))
            next_link = self._next_link(more)
            if len(items) >= limit:
                items = items[:limit]
                break
        return items

    @staticmethod
    def _next_link(payload: dict) -> Optional[str]:
        """Pull the ``links[rel=next].href`` (if any) from a STAC response."""
        for link in payload.get("links", []):
            if link.get("rel") == "next":
                href = link.get("href")
                if href:
                    return href
        return None

    # ----------------------------------------------------- high-level API
    def find_items(
        self,
        collection: str,
        bbox: Tuple[float, float, float, float],
        asset_key: str = "data",
        extra_query: Optional[Dict[str, object]] = None,
    ) -> List[PCItem]:
        """Resolve the catalogue to a list of :class:`PCItem` with signed URLs."""
        token = self.get_sas_token(collection)
        raw_items = self.search_items(collection, bbox, extra_query=extra_query)
        out: List[PCItem] = []
        for item in raw_items:
            assets = item.get("assets", {})
            asset = assets.get(asset_key)
            if asset is None:
                # Fallback: pick the first raster-like asset.
                for k, v in assets.items():
                    if (v.get("type") or "").startswith("image/"):
                        asset = v
                        asset_key = k
                        break
            if asset is None:
                continue
            href = asset.get("href")
            if not href:
                continue
            signed = self.sign_href(href, token)
            out.append(
                PCItem(
                    item_id=item.get("id", ""),
                    href=href,
                    asset_key=asset_key,
                    signed_href=signed,
                )
            )
        return out

    @staticmethod
    def sign_href(href: str, token: str) -> str:
        """Append the SAS token to ``href`` (idempotent)."""
        sep = "&" if "?" in href else "?"
        # Avoid double-appending the same token.
        if token and token in href:
            return href
        return f"{href}{sep}{token}"

    # --------------------------------------------------------------- HTTP
    def _http_get_json(self, url: str) -> dict:
        def _factory(_attempt: int) -> urllib.request.Request:
            return urllib.request.Request(url, headers={"User-Agent": self.user_agent})

        try:
            with _urlopen_with_retry(
                _factory,
                attempts=self.retry_attempts,
                backoff_seconds=self.retry_backoff_seconds,
                timeout=self.timeout,
                what="PC GET",
                feedback=self.feedback,
            ) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise PCError(f"PC GET {url} -> {exc.code} {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise PCError(f"Network error talking to PC: {exc}") from exc

    def _http_post_json(self, url: str, body: dict) -> dict:
        data = json.dumps(body).encode("utf-8")

        def _factory(_attempt: int) -> urllib.request.Request:
            return urllib.request.Request(
                url,
                data=data,
                headers={
                    "User-Agent": self.user_agent,
                    "Content-Type": "application/json",
                },
                method="POST",
            )

        try:
            with _urlopen_with_retry(
                _factory,
                attempts=self.retry_attempts,
                backoff_seconds=self.retry_backoff_seconds,
                timeout=self.timeout,
                what="PC POST",
                feedback=self.feedback,
            ) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise PCError(f"PC POST {url} -> {exc.code} {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise PCError(f"Network error talking to PC: {exc}") from exc

    # ----------------------------------------------------- token persistence
    def _load_token_cache(self) -> None:
        if not self._token_cache_path or not os.path.exists(self._token_cache_path):
            return
        try:
            with open(self._token_cache_path, "r", encoding="utf-8") as fh:
                self._token_cache = json.load(fh)
        except (OSError, json.JSONDecodeError):
            self._token_cache = {}

    def _save_token_cache(self) -> None:
        if not self._token_cache_path:
            return
        try:
            os.makedirs(os.path.dirname(self._token_cache_path) or ".", exist_ok=True)
            with open(self._token_cache_path, "w", encoding="utf-8") as fh:
                json.dump(self._token_cache, fh)
        except OSError:
            pass


# ---------------------------------------------------------------------- utils


_INVALID_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(href: str) -> str:
    """Pick a clean on-disk filename from a URL/asset path."""
    path = href.split("?", 1)[0]
    name = os.path.basename(path) or "pc_item.tif"
    name = _INVALID_FILENAME_CHARS.sub("_", name)
    if not name.lower().endswith((".tif", ".tiff", ".vrt")):
        name = name + ".tif"
    return name


def make_default_pc_client(cache_dir: str) -> PlanetaryComputerClient:
    """Create a PC client writing its token cache under ``cache_dir``."""
    return PlanetaryComputerClient(token_cache_path=os.path.join(cache_dir, "pc_tokens.json"))


__all__ = [
    "PlanetaryComputerClient",
    "PCItem",
    "PCError",
    "download_to_file",
    "make_default_pc_client",
]
