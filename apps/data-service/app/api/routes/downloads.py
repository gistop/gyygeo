from __future__ import annotations

from fastapi import APIRouter, Request, status

from app.schemas.download import DownloadAssetsRequest
from app.schemas.job import JobCreateResponse, JobRecord


router = APIRouter(prefix="/download-jobs", tags=["download-jobs"])


@router.post("", response_model=JobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def download_assets(request: Request, payload: DownloadAssetsRequest) -> JobCreateResponse:
    job = request.app.state.runner.submit_download_assets(payload)
    return JobCreateResponse(job=JobRecord(**job))
