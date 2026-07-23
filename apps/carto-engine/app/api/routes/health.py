from __future__ import annotations

from fastapi import APIRouter, Request

from app.arcpy_engine.environment import probe_arcpy


router = APIRouter(tags=["health"])


@router.get("/health")
def health(request: Request) -> dict:
    settings = request.app.state.settings
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment,
    }


@router.get("/runtime")
def runtime(request: Request) -> dict:
    settings = request.app.state.settings
    return {
        "service": settings.app_name,
        "environment": settings.environment,
        "arcpy": probe_arcpy(settings.python_exe, settings.base_dir),
    }
