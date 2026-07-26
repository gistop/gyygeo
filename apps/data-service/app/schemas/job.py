from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel


JobStatus = Literal["pending", "running", "done", "failed"]


class JobRecord(BaseModel):
    id: str
    type: str
    status: JobStatus
    created_at: str
    updated_at: str
    requested_by: Optional[str] = None
    output_dir: str
    config: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    log_path: Optional[str] = None


class JobListResponse(BaseModel):
    items: List[JobRecord]


class JobCreateResponse(BaseModel):
    job: JobRecord

