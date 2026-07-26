from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel


ProviderStatus = Literal["available", "missing_dependencies", "disabled"]


class ProviderRecord(BaseModel):
    id: str
    name: str
    kind: Literal["stac"]
    status: ProviderStatus
    description: Optional[str] = None
    dependencies: List[str] = []
    missing_dependencies: List[str] = []
    metadata: Dict[str, str] = {}


class ProviderListResponse(BaseModel):
    items: List[ProviderRecord]


class CollectionRecord(BaseModel):
    id: str
    title: Optional[str] = None
    description: Optional[str] = None
    license: Optional[str] = None
    extent: Dict[str, object] = {}
    metadata: Dict[str, object] = {}


class CollectionListResponse(BaseModel):
    items: List[CollectionRecord]

