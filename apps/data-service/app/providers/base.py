from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from app.schemas.prepare import PrepareRasterRequest
from app.schemas.provider import CollectionRecord, ProviderRecord
from app.schemas.search import SearchItem, SearchRequest


class ProviderError(RuntimeError):
    pass


class ProviderNotFoundError(ProviderError):
    pass


class ProviderDependencyError(ProviderError):
    def __init__(self, provider_id: str, missing_dependencies: List[str]) -> None:
        self.provider_id = provider_id
        self.missing_dependencies = missing_dependencies
        joined = ", ".join(missing_dependencies)
        super().__init__(f"Provider '{provider_id}' is missing dependencies: {joined}")


@dataclass(frozen=True)
class PreparedRaster:
    path: Path
    bbox: List[float]
    crs: Optional[str]
    resolution: Optional[float]
    bands: List[str]
    metadata: Dict[str, Any]


@dataclass(frozen=True)
class DownloadedAsset:
    key: str
    path: Path
    size_bytes: int
    media_type: Optional[str]


@dataclass(frozen=True)
class DownloadedAssets:
    output_dir: Path
    assets: List[DownloadedAsset]
    metadata: Dict[str, Any]


class RasterProvider(Protocol):
    provider_id: str

    def describe(self) -> ProviderRecord:
        ...

    def list_collections(self) -> List[CollectionRecord]:
        ...

    def search_items(self, request: SearchRequest) -> List[SearchItem]:
        ...

    def prepare_raster(self, request: PrepareRasterRequest, output_path: Path) -> PreparedRaster:
        ...
