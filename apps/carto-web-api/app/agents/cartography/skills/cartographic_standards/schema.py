from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CartographicStandardsPolicy(BaseModel):
    skill_id: Literal["cartographic_standards"] = "cartographic_standards"
    display_name: str = "Cartographic Standards Skill"
    title_element_name: str = "Title"
    default_position_units: Literal["millimeter", "centimeter", "inch"] = "inch"
    layout_element_aliases: dict[str, str] = Field(default_factory=dict)
    font_family_aliases: dict[str, str] = Field(default_factory=dict)
    font_style_aliases: dict[str, str] = Field(default_factory=dict)


class TextStyleOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element_name: str = Field(min_length=1)
    font_family: Optional[str] = Field(default=None, min_length=1)
    font_size: Optional[float] = Field(default=None, gt=0.0)
    font_style: Optional[str] = Field(default=None, min_length=1)
    required: bool = True

    @model_validator(mode="after")
    def validate_has_operation(self) -> "TextStyleOperation":
        if self.font_family is None and self.font_size is None and self.font_style is None:
            raise ValueError("Text style operation requires font_family, font_size, or font_style.")
        return self


class LayoutElementPositionOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element_name: str = Field(min_length=1)
    anchor: Optional[
        Literal[
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
    ] = None
    x: Optional[float] = None
    y: Optional[float] = None
    offset_x: float = 0.0
    offset_y: float = 0.0
    units: Literal["millimeter", "centimeter", "inch"] = "inch"

    @model_validator(mode="after")
    def validate_position(self) -> "LayoutElementPositionOperation":
        has_anchor = self.anchor is not None
        has_x = self.x is not None
        has_y = self.y is not None
        if has_anchor and (has_x or has_y):
            raise ValueError("Use either anchor or x/y for a layout element position.")
        if has_x != has_y:
            raise ValueError("Layout element x/y position requires both x and y.")
        if not has_anchor and not (has_x and has_y):
            raise ValueError("Layout element position requires anchor or both x and y.")
        return self
