from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CartographicStandardsPolicy(BaseModel):
    skill_id: Literal["cartographic_standards"] = "cartographic_standards"
    display_name: str = "Cartographic Standards Skill"
    title_element_name: str = "Title"
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

