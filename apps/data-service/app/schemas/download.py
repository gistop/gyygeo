from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DownloadAssetsRequest(BaseModel):
    provider: str = Field(default="mpc", min_length=1)
    collection: str = Field(..., min_length=1)
    item_id: str = Field(..., min_length=1)
    assets: List[str] = Field(..., min_length=1)
    requested_by: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
