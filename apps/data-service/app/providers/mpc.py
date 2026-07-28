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
_MPC_TILEJSON_URL = "https://planetarycomputer.microsoft.com/api/data/v1/item/tilejson.json"
_WEB_MERCATOR_HALF_WORLD = 20037508.342789244
_WEB_MERCATOR_INITIAL_RESOLUTION = 156543.03392804097
_WEB_MERCATOR_MAX_LAT = 85.05112878
_TILE_SIZE = 256
_MAX_TILE_FALLBACK_TILES = 256


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
        if request.metadata.get("prepare_strategy") == "mpc_dynamic_tiles":
            return self._prepare_raster_from_mpc_tiles(
                request=request,
                output_path=output_path,
                item=item,
                read_bounds=read_bounds,
                open_error=RuntimeError("MPC dynamic tile strategy requested."),
            )
        sources = []
        try:
            for href in hrefs:
                try:
                    src = rasterio.open(href)
                except Exception as exc:  # noqa: BLE001
                    return self._prepare_raster_from_mpc_tiles(
                        request=request,
                        output_path=output_path,
                        item=item,
                        read_bounds=read_bounds,
                        open_error=exc,
                    )
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

    def _prepare_raster_from_mpc_tiles(
        self,
        *,
        request: PrepareRasterRequest,
        output_path: Path,
        item: Any,
        read_bounds: tuple[float, float, float, float],
        open_error: Exception,
    ) -> PreparedRaster:
        """Fallback that uses MPC dynamic tiles instead of downloading full COG assets."""

        import numpy as np  # type: ignore
        import requests
        import rasterio  # type: ignore
        from rasterio.crs import CRS  # type: ignore
        from rasterio.io import MemoryFile  # type: ignore
        from rasterio.warp import transform_bounds  # type: ignore

        target_crs = CRS.from_string(request.target_crs) if request.target_crs else CRS.from_epsg(3857)
        if target_crs.to_epsg() != 3857:
            raise RuntimeError(
                "GDAL/rasterio could not open the signed MPC COG asset, and the tile fallback "
                "currently supports only EPSG:3857 output. Set target_crs to EPSG:3857."
            ) from open_error

        bbox_crs = CRS.from_string(request.bbox_crs)
        lonlat_bounds = transform_bounds(bbox_crs, CRS.from_epsg(4326), *read_bounds, densify_pts=21)
        lonlat_bounds = _clamp_lonlat_bounds(lonlat_bounds)
        zoom = _choose_tile_zoom(lonlat_bounds, request.target_resolution)

        tilejson = self._fetch_tilejson(request.collection, request.item_id, request.bands)
        minzoom = int(tilejson.get("minzoom", 0))
        maxzoom = int(tilejson.get("maxzoom", 24))
        zoom = min(maxzoom, max(minzoom, zoom))
        tile_template = (tilejson.get("tiles") or [None])[0]
        if not isinstance(tile_template, str) or not tile_template:
            raise RuntimeError("MPC tilejson response did not include a tile URL template.")

        tile_range = _tile_range_for_bounds(lonlat_bounds, zoom)
        while _tile_count(tile_range) > _MAX_TILE_FALLBACK_TILES and zoom > minzoom:
            zoom -= 1
            tile_range = _tile_range_for_bounds(lonlat_bounds, zoom)

        tile_count = _tile_count(tile_range)
        if tile_count > _MAX_TILE_FALLBACK_TILES:
            raise RuntimeError(
                "MPC tile fallback would require too many tiles for this AOI. "
                "Use a smaller AOI or a coarser target_resolution."
            )

        x_min, y_min, x_max, y_max = tile_range
        cols = x_max - x_min + 1
        rows = y_max - y_min + 1
        mosaic = np.zeros((3, rows * _TILE_SIZE, cols * _TILE_SIZE), dtype=np.uint8)

        for y in range(y_min, y_max + 1):
            for x in range(x_min, x_max + 1):
                tile_url = (
                    tile_template
                    .replace("{z}", str(zoom))
                    .replace("{x}", str(x))
                    .replace("{y}", str(y))
                )
                response = requests.get(tile_url, timeout=60)
                response.raise_for_status()
                with MemoryFile(response.content) as memory_file:
                    with memory_file.open() as tile_dataset:
                        tile_data = tile_dataset.read()
                if tile_data.shape[0] >= 3:
                    rgb = tile_data[:3]
                else:
                    rgb = np.repeat(tile_data[:1], 3, axis=0)
                row_offset = (y - y_min) * _TILE_SIZE
                col_offset = (x - x_min) * _TILE_SIZE
                mosaic[
                    :,
                    row_offset : row_offset + _TILE_SIZE,
                    col_offset : col_offset + _TILE_SIZE,
                ] = rgb

        left, top = _tile_upper_left_meters(x_min, y_min, zoom)
        resolution = _tile_resolution(zoom)
        transform = from_origin(left, top, resolution, resolution)
        bounds = (
            left,
            top - mosaic.shape[1] * resolution,
            left + mosaic.shape[2] * resolution,
            top,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        profile = {
            "driver": "GTiff",
            "height": mosaic.shape[1],
            "width": mosaic.shape[2],
            "count": 3,
            "dtype": mosaic.dtype,
            "crs": target_crs,
            "transform": transform,
            "nodata": 0,
            "photometric": "RGB",
        }
        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(mosaic)
            for index, band in enumerate(["red", "green", "blue"], start=1):
                dst.set_band_description(index, band)
            dst.update_tags(
                provider=self.provider_id,
                collection=request.collection,
                item_id=request.item_id,
                source="microsoft-planetary-computer-dynamic-tiles",
            )

        return PreparedRaster(
            path=output_path,
            bbox=[bounds[0], bounds[1], bounds[2], bounds[3]],
            crs=target_crs.to_string(),
            resolution=float(resolution),
            bands=["red", "green", "blue"],
            metadata={
                "provider": self.provider_id,
                "collection": request.collection,
                "item_id": request.item_id,
                "asset_count": len(request.bands),
                "bbox_crs": request.bbox_crs,
                "aoi_type": "polygon" if request.geometry else "bbox",
                "geometry": request.geometry,
                "fallback": "mpc_dynamic_tiles",
                "tile_zoom": zoom,
                "tile_count": tile_count,
                "remote_cog_error": str(open_error),
            },
        )

    def _fetch_tilejson(self, collection: str, item_id: str, bands: List[str]) -> Dict[str, Any]:
        import requests

        params: list[tuple[str, str]] = [
            ("collection", collection),
            ("item", item_id),
            ("format", "png"),
            ("color_formula", "gamma RGB 2.7, saturation 1.5, sigmoidal RGB 15 0.55"),
        ]
        if bands == ["visual"]:
            params.extend([("assets", "visual"), ("asset_bidx", "visual|1,2,3")])
        else:
            for band in bands[:3]:
                params.append(("assets", band))

        response = requests.get(_MPC_TILEJSON_URL, params=params, timeout=60)
        response.raise_for_status()
        return response.json()

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


def _clamp_lonlat_bounds(bounds: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    min_lon, min_lat, max_lon, max_lat = bounds
    return (
        max(-180.0, min(180.0, min_lon)),
        max(-_WEB_MERCATOR_MAX_LAT, min(_WEB_MERCATOR_MAX_LAT, min_lat)),
        max(-180.0, min(180.0, max_lon)),
        max(-_WEB_MERCATOR_MAX_LAT, min(_WEB_MERCATOR_MAX_LAT, max_lat)),
    )


def _choose_tile_zoom(
    lonlat_bounds: tuple[float, float, float, float],
    target_resolution: Optional[float],
) -> int:
    if target_resolution is not None and target_resolution > 0:
        return max(0, min(24, math.ceil(math.log2(_WEB_MERCATOR_INITIAL_RESOLUTION / target_resolution))))

    min_lon, min_lat, max_lon, max_lat = lonlat_bounds
    span = max(abs(max_lon - min_lon), abs(max_lat - min_lat))
    if span <= 0.05:
        return 13
    if span <= 0.2:
        return 11
    if span <= 1:
        return 9
    return 7


def _tile_range_for_bounds(
    lonlat_bounds: tuple[float, float, float, float],
    zoom: int,
) -> tuple[int, int, int, int]:
    min_lon, min_lat, max_lon, max_lat = lonlat_bounds
    x_min, y_max = _lonlat_to_tile(min_lon, min_lat, zoom)
    x_max, y_min = _lonlat_to_tile(max_lon, max_lat, zoom)
    max_index = (2**zoom) - 1
    return (
        max(0, min(max_index, min(x_min, x_max))),
        max(0, min(max_index, min(y_min, y_max))),
        max(0, min(max_index, max(x_min, x_max))),
        max(0, min(max_index, max(y_min, y_max))),
    )


def _lonlat_to_tile(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    lat = max(-_WEB_MERCATOR_MAX_LAT, min(_WEB_MERCATOR_MAX_LAT, lat))
    n = 2**zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return x, y


def _tile_count(tile_range: tuple[int, int, int, int]) -> int:
    x_min, y_min, x_max, y_max = tile_range
    return (x_max - x_min + 1) * (y_max - y_min + 1)


def _tile_resolution(zoom: int) -> float:
    return _WEB_MERCATOR_INITIAL_RESOLUTION / (2**zoom)


def _tile_upper_left_meters(x: int, y: int, zoom: int) -> tuple[float, float]:
    tile_size_meters = (_WEB_MERCATOR_HALF_WORLD * 2.0) / (2**zoom)
    left = -_WEB_MERCATOR_HALF_WORLD + x * tile_size_meters
    top = _WEB_MERCATOR_HALF_WORLD - y * tile_size_meters
    return left, top


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
