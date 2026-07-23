from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas.job import JobListResponse, JobRecord


router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=JobListResponse)
def list_jobs(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> JobListResponse:
    jobs = request.app.state.store.list_jobs(limit=limit)
    return JobListResponse(items=[JobRecord(**job) for job in jobs])


@router.get("/{job_id}", response_model=JobRecord)
def get_job(request: Request, job_id: str) -> JobRecord:
    job = request.app.state.store.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobRecord(**job)
