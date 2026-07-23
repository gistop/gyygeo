from __future__ import annotations

from fastapi import APIRouter, Request, status

from app.schemas.job import JobCreateResponse, JobRecord
from app.schemas.project import RenderPreviewRequest


router = APIRouter(prefix="/render", tags=["render"])


@router.post("/preview", response_model=JobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def render_preview(request: Request, payload: RenderPreviewRequest) -> JobCreateResponse:
    job = request.app.state.runner.submit_render_preview(payload)
    return JobCreateResponse(job=JobRecord(**job))
