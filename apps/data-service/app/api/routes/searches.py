from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.providers.base import ProviderDependencyError, ProviderNotFoundError
from app.schemas.search import SearchRequest, SearchResponse


router = APIRouter(prefix="/searches", tags=["searches"])


@router.post("", response_model=SearchResponse)
def search_items(request: Request, payload: SearchRequest) -> SearchResponse:
    try:
        provider = request.app.state.providers.get(payload.provider)
        return SearchResponse(items=provider.search_items(payload))
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

