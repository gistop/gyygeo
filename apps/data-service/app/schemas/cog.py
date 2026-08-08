from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class CogResolutionRequest(BaseModel):
    provider: str = Field(default="mpc", min_length=1)
    collection: str = Field(..., min_length=1)
    item_id: str = Field(..., min_length=1)
    bands: List[str] = Field(default_factory=lambda: ["red", "green", "blue"], min_length=1)


class CogResolution(BaseModel):
    overview_index: int
    decimation: float
    resolution_meters: float
    width: int
    height: int


class CogResolutionResponse(BaseModel):
    provider: str
    collection: str
    item_id: str
    asset_key: str
    resolutions: List[CogResolution]
