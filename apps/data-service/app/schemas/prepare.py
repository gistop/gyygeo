from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class PrepareOutputOptions(BaseModel):
    format: Literal["geotiff"] = "geotiff"
    purpose: Literal["carto-render"] = "carto-render"


class PrepareRasterRequest(BaseModel):
    provider: str = Field(default="mpc", min_length=1)
    collection: str = Field(..., min_length=1)
    item_id: str = Field(..., min_length=1)
    bbox: List[float] = Field(..., min_length=4, max_length=4)
    geometry: Optional[Dict[str, Any]] = None
    bbox_crs: str = "EPSG:4326"
    bands: List[str] = Field(..., min_length=1)
    target_resolution: Optional[float] = Field(default=None, gt=0.0)
    target_crs: Optional[str] = None
    output: PrepareOutputOptions = Field(default_factory=PrepareOutputOptions)
    requested_by: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
