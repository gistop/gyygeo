from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class DataAcquisitionPolicy(BaseModel):
    skill_id: Literal["data_acquisition"] = "data_acquisition"
    display_name: str = "Data Acquisition Skill"
    default_provider: str = "mpc"
    default_limit: int = Field(default=10, ge=1, le=100)
    min_limit: int = Field(default=1, ge=1)
    max_limit: int = Field(default=100, ge=1)
    selection_strategy: Literal["lowest_cloud_cover_then_earliest_datetime"] = (
        "lowest_cloud_cover_then_earliest_datetime"
    )
    pending_action_type: Literal["select_image"] = "select_image"
    candidate_message: str = "Select one candidate image to continue the expert map task."


class DataAcquisitionSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    collection: str
    bbox: list[float] = Field(min_length=4, max_length=4)
    geometry: Optional[dict[str, Any]] = None
    datetime: Optional[str] = None
    limit: int = Field(ge=1, le=100)
    cloud_cover_lte: Optional[float] = None


class CandidateImage(BaseModel):
    model_config = ConfigDict(extra="allow")

    item_id: str
    provider: Optional[str] = None
    collection: Optional[str] = None
    datetime: Optional[str] = None
    bbox: Optional[list[float]] = None
    cloud_cover: Optional[float] = None


class ImageSelection(BaseModel):
    summary: str
    item: dict[str, Any]


class PendingImageSelectionAction(BaseModel):
    type: Literal["select_image"] = "select_image"
    message: str
    recommended_item_id: Optional[str] = None

