from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


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


class TextTypography(BaseModel):
    element_name: str = Field(..., min_length=1)
    font_family: Optional[str] = Field(default=None, min_length=1)
    font_size: Optional[float] = Field(default=None, gt=0.0)
    font_style: Optional[str] = Field(default=None, min_length=1)
    required: bool = True

    @model_validator(mode="after")
    def validate_typography(self) -> "TextTypography":
        if self.font_family is None and self.font_size is None and self.font_style is None:
            raise ValueError("Text typography requires font_family, font_size, or font_style.")
        return self


LayoutAnchor = Literal[
    "bottom_left",
    "bottom_center",
    "bottom_right",
    "middle_left",
    "center",
    "middle_right",
    "top_left",
    "top_center",
    "top_right",
]
LayoutUnits = Literal["millimeter", "centimeter", "inch"]


class LayoutElementPosition(BaseModel):
    element_name: str = Field(..., min_length=1)
    anchor: Optional[LayoutAnchor] = None
    x: Optional[float] = None
    y: Optional[float] = None
    offset_x: float = 0.0
    offset_y: float = 0.0
    units: Optional[LayoutUnits] = None

    @model_validator(mode="after")
    def validate_position(self) -> "LayoutElementPosition":
        has_anchor = self.anchor is not None
        has_absolute_position = self.x is not None or self.y is not None
        if has_anchor and has_absolute_position:
            raise ValueError("Use either anchor or x/y for a layout element position, not both.")
        if not has_anchor and (self.x is None or self.y is None):
            raise ValueError("A layout element position requires either anchor or both x and y.")
        return self


PageSizeName = Literal["a0", "a1", "a2", "a3", "a4", "letter", "legal"]
PageOrientation = Literal["portrait", "landscape"]
PageUnits = LayoutUnits


class LayoutPage(BaseModel):
    size: Optional[PageSizeName] = None
    orientation: Optional[PageOrientation] = None
    width: Optional[float] = Field(default=None, gt=0.0)
    height: Optional[float] = Field(default=None, gt=0.0)
    units: Optional[PageUnits] = None
    resize_elements: bool = False

    @model_validator(mode="before")
    @classmethod
    def normalize_page_options(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        for key in ("size", "orientation", "units"):
            value = normalized.get(key)
            if isinstance(value, str):
                normalized[key] = value.strip().lower()
        return normalized

    @model_validator(mode="after")
    def validate_page(self) -> "LayoutPage":
        has_size = self.size is not None
        has_width = self.width is not None
        has_height = self.height is not None
        if has_size and (has_width or has_height):
            raise ValueError("Use either page size or custom width/height, not both.")
        if has_width != has_height:
            raise ValueError("Custom page size requires both width and height.")
        if self.units is not None and not (has_width and has_height):
            raise ValueError("Page units can only be used with custom width and height.")
        if not has_size and not has_width and self.orientation is None:
            raise ValueError("Page requires size, custom width/height, or orientation.")
        return self


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
    text_styles: List[TextTypography] = Field(default_factory=list)
    layout_elements: List[LayoutElementPosition] = Field(default_factory=list)
    page: Optional[LayoutPage] = None
    export: ExportOptions = Field(default_factory=ExportOptions)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RenderPreviewRequest(BaseModel):
    project: MapProjectConfig
    requested_by: Optional[str] = None
    dry_run: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)
