from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.providers.base import ProviderDependencyError, ProviderNotFoundError
from app.schemas.tilejson import TilejsonRequest, TilejsonResponse


router = APIRouter(prefix="/tilejson", tags=["tilejson"])


@router.post("", response_model=TilejsonResponse)
def get_tilejson(request: Request, payload: TilejsonRequest) -> TilejsonResponse:
    try:
        provider = request.app.state.providers.get(payload.provider)
        if not hasattr(provider, "get_tilejson"):
            raise HTTPException(
                status_code=400,
                detail=f"Provider does not support tilejson previews: {payload.provider}",
            )
        return provider.get_tilejson(payload)  # type: ignore[attr-defined]
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
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
