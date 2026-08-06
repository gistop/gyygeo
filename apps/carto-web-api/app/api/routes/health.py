from __future__ import annotations

from fastapi import APIRouter, Request


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
        "deepseek_model": settings.deepseek_model,
        "deepseek_configured": bool(settings.deepseek_api_key),
        "tianditu_configured": bool(settings.tianditu_token),
        "data_service_url": settings.data_service_url,
        "carto_engine_url": settings.carto_engine_url,
    }
