from __future__ import annotations

from fastapi import APIRouter, Request, status

from app.schemas.job import JobCreateResponse, JobRecord
from app.schemas.prepare import PrepareRasterRequest


router = APIRouter(prefix="/prepare-jobs", tags=["prepare-jobs"])


@router.post("", response_model=JobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def prepare_raster(request: Request, payload: PrepareRasterRequest) -> JobCreateResponse:
    job = request.app.state.runner.submit_prepare_raster(payload)
    return JobCreateResponse(job=JobRecord(**job))

