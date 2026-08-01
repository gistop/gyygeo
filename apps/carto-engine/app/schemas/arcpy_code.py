from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.project import TextTypography


class ArcPyCodeRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=200000)
    requested_by: Optional[str] = None
    project_name: str = Field(default="expert-arcpy-code", min_length=1)
    template_id: str = Field(default="default", min_length=1)
    output_format: Literal["jpg", "png", "pdf"] = "jpg"
    dpi: int = Field(default=300, ge=72, le=600)
    text_styles: List[TextTypography] = Field(default_factory=list)
    context: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
