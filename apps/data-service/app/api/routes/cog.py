from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.schemas.cog import CogResolutionRequest, CogResolutionResponse


router = APIRouter(prefix="/cog-resolutions", tags=["cog"])


@router.post("", response_model=CogResolutionResponse)
def get_cog_resolutions(
    request: Request,
    payload: CogResolutionRequest,
) -> CogResolutionResponse:
    provider = request.app.state.providers.get(payload.provider)
    if not hasattr(provider, "get_cog_resolutions"):
        raise HTTPException(
            status_code=400,
            detail=f"Provider does not support COG resolutions: {payload.provider}",
        )
    result = provider.get_cog_resolutions(  # type: ignore[attr-defined]
        payload.collection,
        payload.item_id,
        payload.bands,
    )
    return CogResolutionResponse(**result)
