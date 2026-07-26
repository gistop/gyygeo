from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.providers.base import ProviderDependencyError, ProviderNotFoundError
from app.schemas.provider import CollectionListResponse, ProviderListResponse, ProviderRecord


router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("", response_model=ProviderListResponse)
def list_providers(request: Request) -> ProviderListResponse:
    providers = request.app.state.providers.list()
    return ProviderListResponse(items=[provider.describe() for provider in providers])


@router.get("/{provider_id}", response_model=ProviderRecord)
def get_provider(request: Request, provider_id: str) -> ProviderRecord:
    try:
        return request.app.state.providers.get(provider_id).describe()
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{provider_id}/collections", response_model=CollectionListResponse)
def list_collections(request: Request, provider_id: str) -> CollectionListResponse:
    try:
        provider = request.app.state.providers.get(provider_id)
        return CollectionListResponse(items=provider.list_collections())
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProviderDependencyError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": str(exc),
                "missing_dependencies": exc.missing_dependencies,
            },
        ) from exc

