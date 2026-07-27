from __future__ import annotations

import importlib.util
import math
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

from rasterio.transform import from_origin  # type: ignore

from app.providers.base import DownloadedAsset, DownloadedAssets, PreparedRaster, ProviderDependencyError
from app.schemas.download import DownloadAssetsRequest
from app.schemas.prepare import PrepareRasterRequest
from app.schemas.provider import CollectionRecord, ProviderRecord
from app.schemas.search import AssetSummary, SearchItem, SearchRequest


_MPC_COLLECTION_HINTS = {
    "landsat-c2-l2": "Landsat Collection 2 Level-2",
    "sentinel-2-l2a": "Sentinel-2 Level-2A",
}


class MpcProvider:
    provider_id = "mpc"

    def __init__(self, stac_url: str) -> None:
        self.stac_url = stac_url

    def describe(self) -> ProviderRecord:
        missing = self._missing_dependencies()
        return ProviderRecord(
            id=self.provider_id,
            name="Microsoft Planetary Computer",
            kind="stac",
            status="missing_dependencies" if missing else "available",
            description="STAC provider for Microsoft Planetary Computer raster assets.",
            dependencies=["pystac-client", "planetary-computer", "rasterio", "numpy"],
            missing_dependencies=missing,
            metadata={"stac_url": self.stac_url},
        )

    def list_collections(self) -> List[CollectionRecord]:
        self._ensure_search_dependencies()
        from pystac_client import Client  # type: ignore

        client = Client.open(self.stac_url)
        collections = []
        for collection in client.get_collections():
            collections.append(
                CollectionRecord(
                    id=collection.id,
                    title=collection.title,
                    description=collection.description,
                    license=(collection.extra_fields or {}).get("license"),
                    extent=_safe_to_dict(collection.extent),
                    metadata={"provider": self.provider_id},
                )
            )
        return collections

    def search_items(self, request: SearchRequest) -> List[SearchItem]:
        self._ensure_search_dependencies()
        from pystac_client import Client  # type: ignore

        client = Client.open(self.stac_url)
        query: Dict[str, Any] = dict(request.query)
        if request.cloud_cover_lte is not None:
            query.setdefault("eo:cloud_cover", {"lte": request.cloud_cover_lte})

        search_kwargs: Dict[str, Any] = {
            "collections": [request.collection],
            "datetime": request.datetime,
            "query": query or None,
            "limit": request.limit,
        }
        if request.geometry:
            search_kwargs["intersects"] = request.geometry
        else:
            search_kwargs["bbox"] = request.bbox

        search = client.search(**search_kwargs)
        return [
            self._normalize_item(item, request.collection)
            for item in list(search.items())[: request.limit]
        ]

    def prepare_raster(self, request: PrepareRasterRequest, output_path: Path) -> PreparedRaster:
        self._ensure_prepare_dependencies()
        import numpy as np  # type: ignore
        import planetary_computer  # type: ignore
        import rasterio  # type: ignore
        from rasterio.crs import CRS  # type: ignore
        from rasterio.enums import Resampling  # type: ignore
        from rasterio.features import geometry_mask  # type: ignore
        from rasterio.transform import array_bounds
        from rasterio.vrt import WarpedVRT  # type: ignore
        from rasterio.warp import transform_bounds, transform_geom  # type: ignore
        from rasterio.windows import from_bounds  # type: ignore

        items = self._search_by_id(request.collection, request.item_id)
        if not items:
            raise RuntimeError(
                f"Item not found in provider '{self.provider_id}': "
                f"{request.collection}/{request.item_id}"
            )
        item = planetary_computer.sign(items[0])

        hrefs = []
        missing_assets = []
        for band in request.bands:
            asset = item.assets.get(band)
            if asset is None:
                missing_assets.append(band)
            else:
                hrefs.append(asset.href)
        if missing_assets:
            raise RuntimeError(f"Missing assets on item {request.item_id}: {', '.join(missing_assets)}")

        target_crs = CRS.from_string(request.target_crs) if request.target_crs else None
        bbox_crs = CRS.from_string(request.bbox_crs)
        read_bounds = _geometry_bounds(request.geometry) if request.geometry else tuple(request.bbox)
        sources = []
        try:
            for href in hrefs:
                try:
                    src = rasterio.open(href)
                except Exception as exc:  # noqa: BLE001
                    raise RuntimeError(
                        "GDAL/rasterio could not open the signed MPC COG asset. "
                        "Verify that the running environment supports remote HTTPS COG reads."
                    ) from exc
                dst_crs = target_crs or src.crs
                target_bounds = transform_bounds(bbox_crs, dst_crs, *read_bounds, densify_pts=21)
                target_geometry = (
                    transform_geom(bbox_crs, dst_crs, request.geometry)
                    if request.geometry
                    else None
                )

                if request.target_resolution is not None:
                    transform = _target_transform(target_bounds, request.target_resolution)
                    width = max(
                        1,
                        math.ceil(
                            (target_bounds[2] - target_bounds[0])
                            / request.target_resolution
                        ),
                    )
                    height = max(
                        1,
                        math.ceil(
                            (target_bounds[3] - target_bounds[1])
                            / request.target_resolution
                        ),
                    )
                    vrt = WarpedVRT(
                        src,
                        crs=dst_crs,
                        transform=transform,
                        width=width,
                        height=height,
                        resampling=Resampling.bilinear,
                    )
                    data = vrt.read(1, masked=True)
                    transform = vrt.transform
                else:
                    vrt_options: Dict[str, Any] = {"resampling": Resampling.bilinear}
                    if target_crs is not None:
                        vrt_options["crs"] = target_crs
                    vrt = WarpedVRT(src, **vrt_options)
                    target_bounds = transform_bounds(
                        bbox_crs,
                        vrt.crs,
                        *read_bounds,
                        densify_pts=21,
                    )
                    target_geometry = (
                        transform_geom(bbox_crs, vrt.crs, request.geometry)
                        if request.geometry
                        else None
                    )
                    window = (
                        from_bounds(*target_bounds, transform=vrt.transform)
                        .round_offsets()
                        .round_lengths()
                    )
                    data = vrt.read(1, window=window, boundless=True, masked=True)
                    transform = vrt.window_transform(window)
                if target_geometry:
                    inside_geometry = geometry_mask(
                        [target_geometry],
                        out_shape=data.shape,
                        transform=transform,
                        invert=True,
                    )
                    data = np.ma.array(data, mask=np.ma.getmaskarray(data) | ~inside_geometry)
                sources.append((src, vrt, data, transform))

            arrays = [source[2] for source in sources]
            first_shape = arrays[0].shape
            if any(array.shape != first_shape for array in arrays):
                raise RuntimeError("Prepared band windows do not have matching shapes.")
            stacked = np.ma.stack(arrays)
            output_data = stacked.filled(0) if np.ma.isMaskedArray(stacked) else stacked

            reference_vrt = sources[0][1]
            transform = sources[0][3]
            crs = reference_vrt.crs
            output_path.parent.mkdir(parents=True, exist_ok=True)
            profile = {
                "driver": "GTiff",
                "height": output_data.shape[1],
                "width": output_data.shape[2],
                "count": output_data.shape[0],
                "dtype": output_data.dtype,
                "crs": crs,
                "transform": transform,
                "nodata": 0,
                "compress": "deflate",
                "tiled": True,
                "blockxsize": 512,
                "blockysize": 512,
            }
            with rasterio.open(output_path, "w", **profile) as dst:
                dst.write(output_data)
                for index, band in enumerate(request.bands, start=1):
                    dst.set_band_description(index, band)
                dst.update_tags(
                    provider=self.provider_id,
                    collection=request.collection,
                    item_id=request.item_id,
                    source="microsoft-planetary-computer",
                )

            bounds = array_bounds(output_data.shape[1], output_data.shape[2], transform)
            resolution = abs(transform.a) if transform else request.target_resolution
            return PreparedRaster(
                path=output_path,
                bbox=[bounds[0], bounds[1], bounds[2], bounds[3]],
                crs=crs.to_string() if crs else None,
                resolution=float(resolution) if resolution is not None else None,
                bands=request.bands,
                metadata={
                    "provider": self.provider_id,
                    "collection": request.collection,
                    "item_id": request.item_id,
                    "asset_count": len(hrefs),
                    "bbox_crs": request.bbox_crs,
                    "aoi_type": "polygon" if request.geometry else "bbox",
                    "geometry": request.geometry,
                },
            )
        finally:
            for src, vrt, _data, _transform in sources:
                vrt.close()
                src.close()

    def download_assets(self, request: DownloadAssetsRequest, output_dir: Path) -> DownloadedAssets:
        self._ensure_search_dependencies()
        import planetary_computer  # type: ignore
        import requests

        items = self._search_by_id(request.collection, request.item_id)
        if not items:
            raise RuntimeError(
                f"Item not found in provider '{self.provider_id}': "
                f"{request.collection}/{request.item_id}"
            )
        item = planetary_computer.sign(items[0])

        output_dir.mkdir(parents=True, exist_ok=True)
        downloaded = []
        missing_assets = []
        for key in request.assets:
            asset = item.assets.get(key)
            if asset is None:
                missing_assets.append(key)
                continue

            path = output_dir / _asset_filename(key, asset.href)
            with requests.get(asset.href, stream=True, timeout=60) as response:
                response.raise_for_status()
                with path.open("wb") as file_obj:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            file_obj.write(chunk)

            downloaded.append(
                DownloadedAsset(
                    key=key,
                    path=path,
                    size_bytes=path.stat().st_size,
                    media_type=getattr(asset, "media_type", None),
                )
            )

        if missing_assets:
            raise RuntimeError(f"Missing assets on item {request.item_id}: {', '.join(missing_assets)}")

        return DownloadedAssets(
            output_dir=output_dir,
            assets=downloaded,
            metadata={
                "provider": self.provider_id,
                "collection": request.collection,
                "item_id": request.item_id,
                "asset_count": len(downloaded),
            },
        )

    def _search_by_id(self, collection: str, item_id: str) -> List[Any]:
        self._ensure_search_dependencies()
        from pystac_client import Client  # type: ignore

        client = Client.open(self.stac_url)
        search = client.search(collections=[collection], ids=[item_id], limit=1)
        return list(search.items())

    def _normalize_item(self, item: Any, collection: str) -> SearchItem:
        assets = []
        for key, asset in item.assets.items():
            eo_bands = []
            for band in getattr(asset, "extra_fields", {}).get("eo:bands", []) or []:
                if isinstance(band, dict):
                    eo_bands.append(str(band.get("name") or band.get("common_name") or ""))
            assets.append(
                AssetSummary(
                    key=key,
                    title=getattr(asset, "title", None),
                    media_type=getattr(asset, "media_type", None),
                    roles=list(getattr(asset, "roles", []) or []),
                    eo_bands=[band for band in eo_bands if band],
                )
            )

        props = getattr(item, "properties", {}) or {}
        return SearchItem(
            provider=self.provider_id,
            collection=collection,
            item_id=item.id,
            datetime=_datetime_to_string(props.get("datetime") or getattr(item, "datetime", None)),
            bbox=list(getattr(item, "bbox", None) or []),
            cloud_cover=props.get("eo:cloud_cover"),
            assets=assets,
            metadata={
                "platform": props.get("platform"),
                "constellation": props.get("constellation"),
                "title": _MPC_COLLECTION_HINTS.get(collection),
            },
        )

    def _ensure_search_dependencies(self) -> None:
        missing = [
            dependency
            for dependency in ["pystac-client", "planetary-computer"]
            if _missing_distribution(dependency)
        ]
        if missing:
            raise ProviderDependencyError(self.provider_id, missing)

    def _ensure_prepare_dependencies(self) -> None:
        missing = self._missing_dependencies()
        if missing:
            raise ProviderDependencyError(self.provider_id, missing)

    def _missing_dependencies(self) -> List[str]:
        return [
            dependency
            for dependency in ["pystac-client", "planetary-computer", "rasterio", "numpy"]
            if _missing_distribution(dependency)
        ]


def _missing_distribution(package_name: str) -> bool:
    import_name = package_name.replace("-", "_")
    return importlib.util.find_spec(import_name) is None


def _datetime_to_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _safe_to_dict(value: Any) -> Dict[str, object]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return dict(value) if isinstance(value, dict) else {}


def _target_transform(bounds: tuple[float, float, float, float], resolution: float) -> Any:
    left, _bottom, _right, top = bounds
    return from_origin(left, top, resolution, resolution)


def _geometry_bounds(geometry: Dict[str, Any]) -> tuple[float, float, float, float]:
    coordinates = geometry.get("coordinates")
    if geometry.get("type") != "Polygon" or not isinstance(coordinates, list):
        raise RuntimeError("Only GeoJSON Polygon AOI geometry is supported.")

    points = []
    for ring in coordinates:
        if not isinstance(ring, list):
            continue
        for coordinate in ring:
            if (
                isinstance(coordinate, list)
                and len(coordinate) >= 2
                and isinstance(coordinate[0], (int, float))
                and isinstance(coordinate[1], (int, float))
            ):
                points.append((float(coordinate[0]), float(coordinate[1])))

    if len(points) < 4:
        raise RuntimeError("Polygon AOI geometry must include at least three vertices.")

    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _asset_filename(key: str, href: str) -> str:
    parsed = urlparse(href)
    basename = Path(unquote(parsed.path)).name
    if basename:
        return basename
    return f"{key}.bin"
