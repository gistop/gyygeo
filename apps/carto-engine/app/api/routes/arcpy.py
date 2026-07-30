from __future__ import annotations

from fastapi import APIRouter, Request, status

from app.schemas.arcpy_code import ArcPyCodeRequest
from app.schemas.job import JobCreateResponse, JobRecord


router = APIRouter(prefix="/arcpy", tags=["arcpy"])


@router.post("/code", response_model=JobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
def run_arcpy_code(request: Request, payload: ArcPyCodeRequest) -> JobCreateResponse:
    job = request.app.state.runner.submit_arcpy_code(payload)
    return JobCreateResponse(job=JobRecord(**job))
