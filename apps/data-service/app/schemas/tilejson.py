from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TilejsonRequest(BaseModel):
    provider: str = Field(default="mpc", min_length=1)
    collection: str = Field(..., min_length=1)
    item_id: str = Field(..., min_length=1)
    bands: List[str] = Field(default_factory=lambda: ["red", "green", "blue"])


class TilejsonResponse(BaseModel):
    provider: str
    collection: str
    item_id: str
    tiles: List[str]
    tilejson: Dict[str, Any]
    bounds: Optional[List[float]] = None
    minzoom: Optional[int] = None
    maxzoom: Optional[int] = None
