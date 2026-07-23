from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class LayerConfig(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    data_source: Optional[str] = None
    visible: bool = True
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    definition_query: Optional[str] = None
    style: Dict[str, Any] = Field(default_factory=dict)


class MapExtent(BaseModel):
    xmin: float
    ymin: float
    xmax: float
    ymax: float
    spatial_reference_wkid: Optional[int] = None


class LayoutText(BaseModel):
    element_name: str = Field(..., min_length=1)
    text: str


class ExportOptions(BaseModel):
    format: Literal["png", "jpg", "pdf"] = "png"
    dpi: int = Field(default=150, ge=72, le=600)
    layout_name: Optional[str] = None
    map_frame_name: Optional[str] = None


class MapProjectConfig(BaseModel):
    project_name: str = Field(..., min_length=1)
    template_id: str = Field(default="default", min_length=1)
    title: Optional[str] = None
    remove_layers: List[str] = Field(default_factory=list)
    layers: List[LayerConfig] = Field(default_factory=list)
    extent: Optional[MapExtent] = None
    fit_to_layers: bool = False
    fit_layer_names: List[str] = Field(default_factory=list)
    fit_padding: float = Field(default=0.08, ge=0.0, le=1.0)
    layout_text: List[LayoutText] = Field(default_factory=list)
    export: ExportOptions = Field(default_factory=ExportOptions)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RenderPreviewRequest(BaseModel):
    project: MapProjectConfig
    requested_by: Optional[str] = None
    dry_run: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)
