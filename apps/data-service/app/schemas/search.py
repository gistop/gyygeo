from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    provider: str = Field(default="mpc", min_length=1)
    collection: str = Field(..., min_length=1)
    bbox: List[float] = Field(..., min_length=4, max_length=4)
    datetime: Optional[str] = None
    limit: int = Field(default=10, ge=1, le=100)
    cloud_cover_lte: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    query: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AssetSummary(BaseModel):
    key: str
    title: Optional[str] = None
    media_type: Optional[str] = None
    roles: List[str] = []
    eo_bands: List[str] = []
    metadata: Dict[str, Any] = {}


class SearchItem(BaseModel):
    provider: str
    collection: str
    item_id: str
    datetime: Optional[str] = None
    bbox: List[float] = []
    cloud_cover: Optional[float] = None
    assets: List[AssetSummary] = []
    metadata: Dict[str, Any] = {}


class SearchResponse(BaseModel):
    items: List[SearchItem]

