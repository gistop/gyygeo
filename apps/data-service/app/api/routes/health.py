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
    providers = [provider.describe() for provider in request.app.state.providers.list()]
    return {
        "service": settings.app_name,
        "environment": settings.environment,
        "providers": [provider.model_dump(mode="json") for provider in providers],
    }

