"""Registry of DEM sources available to the plugin.

All sources in this MVP share a single
:class:`PlanetaryComputerClient` so the SAS token is fetched once per
collection and reused across the run.
"""
from __future__ import annotations

import os
from typing import Dict, List, Type

from ..core.pc_client import PlanetaryComputerClient
from .base import BaseDEMSource
from .fabdem import FABDEMSource
from .glo30 import GLO30Source
from .nasadem import NASADEMSource
from .aw3d30 import AW3D30Source
from .srtm import SRTMSource

_REGISTRY: Dict[str, Type[BaseDEMSource]] = {
    cls.id: cls
    for cls in (FABDEMSource, GLO30Source, NASADEMSource, AW3D30Source, SRTMSource)
}


def available_sources() -> List[Type[BaseDEMSource]]:
    return list(_REGISTRY.values())


def get_source(
    source_id: str,
    cache_dir: str,
    pc_client: PlanetaryComputerClient | None = None,
) -> BaseDEMSource:
    """Build an instance of the source with the given id."""
    cls = _REGISTRY[source_id]
    return cls(cache_dir, pc_client=pc_client)


def build_shared_pc_client(cache_dir: str) -> PlanetaryComputerClient:
    """Create a single client whose token cache lives under ``cache_dir``."""
    os.makedirs(cache_dir, exist_ok=True)
    return PlanetaryComputerClient(
        token_cache_path=os.path.join(cache_dir, "pc_tokens.json"),
    )


__all__ = ["available_sources", "get_source", "build_shared_pc_client"]
