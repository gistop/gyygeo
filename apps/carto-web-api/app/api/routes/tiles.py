from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, HTTPException, Request, Response


router = APIRouter(prefix="/tiles", tags=["tiles"])


@router.get("/tianditu/{layer}_w/{z}/{x}/{y}")
def tianditu_web_mercator_tile(request: Request, layer: str, z: int, x: int, y: int) -> Response:
    settings = request.app.state.settings
    if not settings.tianditu_token:
        raise HTTPException(
            status_code=503,
            detail="Tianditu token is not configured. Set GYYGEO_WEB_API_TIANDITU_TOKEN.",
        )
    if layer not in {"vec", "cva"}:
        raise HTTPException(status_code=404, detail="Unsupported Tianditu layer.")
    if z < 0 or x < 0 or y < 0:
        raise HTTPException(status_code=400, detail="Tile coordinates must be non-negative.")

    base_url = settings.tianditu_vec_w_wmts_url if layer == "vec" else settings.tianditu_cva_w_wmts_url
    upstream_url = _wmts_url(
        base_url,
        {
            "SERVICE": "WMTS",
            "REQUEST": "GetTile",
            "VERSION": "1.0.0",
            "LAYER": layer,
            "STYLE": "default",
            "TILEMATRIXSET": "w",
            "FORMAT": "tiles",
            "TILEMATRIX": str(z),
            "TILEROW": str(y),
            "TILECOL": str(x),
            "tk": settings.tianditu_token,
        },
    )
    upstream_request = urllib.request.Request(
        upstream_url,
        method="GET",
        headers={
            "Accept": "image/*,*/*;q=0.8",
            "User-Agent": "gyygeo-carto-web-api/0.1.0",
        },
    )

    try:
        with urllib.request.urlopen(upstream_request, timeout=20) as upstream_response:
            body = upstream_response.read()
            content_type = upstream_response.headers.get("Content-Type") or "image/png"
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=exc.code, detail="Tianditu tile request failed.") from exc
    except urllib.error.URLError as exc:
        raise HTTPException(status_code=502, detail=f"Tianditu tile request failed: {exc.reason}") from exc

    return Response(
        content=body,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


def _wmts_url(base_url: str, params: dict[str, str]) -> str:
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urllib.parse.urlencode(params)}"
