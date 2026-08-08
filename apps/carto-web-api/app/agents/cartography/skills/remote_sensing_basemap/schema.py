from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class RemoteSensingBasemapPolicy(BaseModel):
    skill_id: Literal["remote_sensing_basemap"] = "remote_sensing_basemap"
    display_name: str = "Remote Sensing Basemap Skill"
    default_bands: list[str] = Field(default_factory=lambda: ["red", "green", "blue"])
    default_target_crs: str = "EPSG:3857"
    default_target_resolution: float = 30
    bbox_crs: str = "EPSG:4326"
    output_format: Literal["geotiff"] = "geotiff"
    output_purpose: Literal["carto-render"] = "carto-render"
    requested_by: str = "gyygeo-agent"
    prepare_strategy: str = "mpc_cog"
    fallback_strategy: str = "mpc_dynamic_tiles"
    layer_name: str = "Prepared Remote Sensing Basemap"


class RemoteSensingBasemapPrepareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    collection: str
    item_id: str
    bbox: list[float] = Field(min_length=4, max_length=4)
    geometry: Optional[dict[str, Any]] = None
    bbox_crs: str
    bands: list[str]
    target_resolution: Optional[float] = None
    target_crs: Optional[str] = None
    requested_by: str
    output: dict[str, str]
    metadata: dict[str, Any]
