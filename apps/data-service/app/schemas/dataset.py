from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel


DatasetStatus = Literal["preparing", "ready", "failed", "expired"]


class DatasetRecord(BaseModel):
    id: str
    status: DatasetStatus
    provider: str
    collection: str
    item_id: str
    type: Literal["raster", "asset_bundle"] = "raster"
    created_at: str
    updated_at: str
    path: Optional[str] = None
    bbox: List[float]
    crs: Optional[str] = None
    resolution: Optional[float] = None
    bands: List[str]
    metadata: Dict[str, Any] = {}
    error: Optional[str] = None


class DatasetListResponse(BaseModel):
    items: List[DatasetRecord]
