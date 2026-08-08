from __future__ import annotations

import importlib.util
import math
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

from rasterio.transform import from_origin  # type: ignore

from app.providers.base import DownloadedAsset, DownloadedAssets, PreparedRaster, ProviderDependencyError
from app.schemas.download import DownloadAssetsRequest
from app.schemas.prepare import PrepareRasterRequest
from app.schemas.provider import CollectionRecord, ProviderRecord
from app.schemas.search import AssetSummary, SearchItem, SearchRequest
from app.schemas.tilejson import TilejsonRequest, TilejsonResponse


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
_MAX_COG_RANGE_TILES = 4096
_COG_RANGE_CHUNK_BYTES = 64 * 1024


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
        prepare_strategy = str(request.metadata.get("prepare_strategy") or "mpc_cog")
        fallback_strategy = str(request.metadata.get("fallback_strategy") or "mpc_dynamic_tiles")
        if prepare_strategy == "mpc_dynamic_tiles":
            return self._prepare_raster_from_mpc_tiles(
                request=request,
                output_path=output_path,
                item=item,
                read_bounds=read_bounds,
                open_error=RuntimeError("MPC dynamic tile strategy requested."),
            )
        if prepare_strategy == "mpc_cog":
            try:
                return self._prepare_raster_from_mpc_cog(
                    request=request,
                    output_path=output_path,
                    item=item,
                    hrefs=hrefs,
                    read_bounds=read_bounds,
                )
            except Exception as exc:  # noqa: BLE001
                if _looks_like_output_write_error(exc):
                    raise
                if fallback_strategy == "mpc_dynamic_tiles":
                    return self._prepare_raster_from_mpc_tiles(
                        request=request,
                        output_path=output_path,
                        item=item,
                        read_bounds=read_bounds,
                        open_error=exc,
                    )
                raise
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

    def _prepare_raster_from_mpc_cog(
        self,
        *,
        request: PrepareRasterRequest,
        output_path: Path,
        item: Any,
        hrefs: List[str],
        read_bounds: tuple[float, float, float, float],
    ) -> PreparedRaster:
        """Read MPC COG assets by AOI and overview using HTTP range requests."""

        import numpy as np  # type: ignore
        import rasterio  # type: ignore
        from rasterio.crs import CRS  # type: ignore
        from rasterio.enums import Resampling  # type: ignore
        from rasterio.features import geometry_mask  # type: ignore
        from rasterio.transform import Affine  # type: ignore
        from rasterio.warp import (  # type: ignore
            calculate_default_transform,
            reproject,
            transform_bounds,
            transform_geom,
        )
        from rasterio.windows import from_bounds  # type: ignore

        source_epsg = _source_epsg(getattr(item, "properties", {}) or {})
        source_transform_values = (getattr(item, "properties", {}) or {}).get("proj:transform")
        if not source_epsg or not source_transform_values:
            raise RuntimeError(
                "MPC item is missing proj:epsg/proj:code or proj:transform metadata."
            )
        source_crs = CRS.from_epsg(source_epsg)
        bbox_crs = CRS.from_string(request.bbox_crs)
        base_transform = _source_affine([float(value) for value in source_transform_values])
        requested_overview_index = _optional_int(request.metadata.get("overview_index"))

        selected_overview_index: Optional[int] = None
        selected_resolution: Optional[float] = None
        selected_decimation: Optional[float] = None
        arrays = []
        output_transform = None
        output_crs = source_crs
        total_cog_tiles = 0

        for band, href in zip(request.bands, hrefs):
            metadata_levels = _read_cog_metadata_levels(href)
            base_metadata = metadata_levels[0]
            metadata = _select_cog_level(
                metadata_levels=metadata_levels,
                base_transform=base_transform,
                target_resolution=request.target_resolution,
                requested_overview_index=(
                    selected_overview_index
                    if selected_overview_index is not None
                    else requested_overview_index
                ),
                asset_key=band,
            )
            selected_overview_index = metadata.overview_index
            transform = _cog_level_transform(base_transform, base_metadata, metadata)
            resolution = _resolution_meters(transform)
            selected_resolution = resolution
            selected_decimation = _cog_decimation(base_metadata, metadata)
            _ensure_supported_cog(metadata, band)

            source_bounds = rasterio.transform.array_bounds(
                metadata.image_height,
                metadata.image_width,
                transform,
            )
            target_bounds = transform_bounds(
                bbox_crs,
                source_crs,
                read_bounds[0],
                read_bounds[1],
                read_bounds[2],
                read_bounds[3],
                densify_pts=21,
            )
            clipped = (
                max(target_bounds[0], source_bounds[0]),
                max(target_bounds[1], source_bounds[1]),
                min(target_bounds[2], source_bounds[2]),
                min(target_bounds[3], source_bounds[3]),
            )
            if clipped[0] >= clipped[2] or clipped[1] >= clipped[3]:
                raise RuntimeError(f"AOI does not overlap asset {band}.")

            window = from_bounds(*clipped, transform=transform)
            col_start = max(0, math.floor(window.col_off))
            row_start = max(0, math.floor(window.row_off))
            col_stop = min(metadata.image_width, math.ceil(window.col_off + window.width))
            row_stop = min(metadata.image_height, math.ceil(window.row_off + window.height))
            if col_stop <= col_start or row_stop <= row_start:
                raise RuntimeError(f"AOI produced an empty COG window for asset {band}.")

            cog_tile_count = _cog_window_tile_count(
                metadata,
                row_start,
                row_stop,
                col_start,
                col_stop,
            )
            total_cog_tiles += cog_tile_count
            if cog_tile_count > _MAX_COG_RANGE_TILES:
                raise RuntimeError(
                    f"COG AOI read for {band} would require {cog_tile_count} internal tiles. "
                    "Use a coarser target_resolution or smaller AOI."
                )

            data = _read_cog_window(href, metadata, row_start, row_stop, col_start, col_stop)
            band_transform = transform * Affine.translation(col_start, row_start)
            if request.geometry is not None:
                projected_geometry = transform_geom(bbox_crs, source_crs, request.geometry)
                inside = geometry_mask(
                    [projected_geometry],
                    out_shape=data.shape,
                    transform=band_transform,
                    invert=True,
                )
                data = np.where(inside, data, np.zeros((), dtype=data.dtype))

            if output_transform is None:
                output_transform = band_transform
            elif data.shape != arrays[0].shape or band_transform != output_transform:
                raise RuntimeError("COG band windows do not share the same grid.")
            arrays.append(data)

        if not arrays or output_transform is None:
            raise RuntimeError("COG preparation did not read any raster bands.")

        output_data = np.stack(arrays)
        requested_target_crs = CRS.from_string(request.target_crs) if request.target_crs else source_crs
        if requested_target_crs != source_crs:
            bounds = rasterio.transform.array_bounds(
                output_data.shape[1],
                output_data.shape[2],
                output_transform,
            )
            transform_options: Dict[str, Any] = {}
            if request.target_resolution:
                transform_options["resolution"] = request.target_resolution
            dst_transform, dst_width, dst_height = calculate_default_transform(
                source_crs,
                requested_target_crs,
                output_data.shape[2],
                output_data.shape[1],
                *bounds,
                **transform_options,
            )
            reprojected = np.zeros(
                (output_data.shape[0], dst_height, dst_width),
                dtype=output_data.dtype,
            )
            for band_index in range(output_data.shape[0]):
                reproject(
                    source=output_data[band_index],
                    destination=reprojected[band_index],
                    src_transform=output_transform,
                    src_crs=source_crs,
                    dst_transform=dst_transform,
                    dst_crs=requested_target_crs,
                    resampling=Resampling.bilinear,
                    src_nodata=0,
                    dst_nodata=0,
                )
            output_data = reprojected
            output_transform = dst_transform
            output_crs = requested_target_crs

        output_path.parent.mkdir(parents=True, exist_ok=True)
        profile = {
            "driver": "GTiff",
            "height": output_data.shape[1],
            "width": output_data.shape[2],
            "count": output_data.shape[0],
            "dtype": output_data.dtype,
            "crs": output_crs,
            "transform": output_transform,
            "nodata": 0,
            "compress": "deflate",
            "tiled": True,
            "blockxsize": 512,
            "blockysize": 512,
        }
        if output_data.shape[0] == 3:
            profile["photometric"] = "RGB"
        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(output_data)
            for index, band in enumerate(request.bands, start=1):
                dst.set_band_description(index, band)
            dst.update_tags(
                provider=self.provider_id,
                collection=request.collection,
                item_id=request.item_id,
                source="microsoft-planetary-computer",
                source_read="http-range-cog-tiles",
                prepare_strategy="mpc_cog",
                overview_index=str(selected_overview_index),
                resolution_meters=str(selected_resolution),
            )

        bounds = rasterio.transform.array_bounds(
            output_data.shape[1],
            output_data.shape[2],
            output_transform,
        )
        return PreparedRaster(
            path=output_path,
            bbox=[bounds[0], bounds[1], bounds[2], bounds[3]],
            crs=output_crs.to_string() if output_crs else None,
            resolution=float(abs(output_transform.a)) if output_transform else selected_resolution,
            bands=request.bands,
            metadata={
                "provider": self.provider_id,
                "collection": request.collection,
                "item_id": request.item_id,
                "asset_count": len(hrefs),
                "bbox_crs": request.bbox_crs,
                "aoi_type": "polygon" if request.geometry else "bbox",
                "geometry": request.geometry,
                "prepare_strategy": "mpc_cog",
                "source_read": "http-range-cog-tiles",
                "overview_index": selected_overview_index,
                "cog_resolution_meters": selected_resolution,
                "cog_decimation": selected_decimation,
                "cog_tile_count": total_cog_tiles,
                "fallback_strategy": request.metadata.get(
                    "fallback_strategy",
                    "mpc_dynamic_tiles",
                ),
            },
        )

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

    def get_tilejson(self, request: TilejsonRequest) -> TilejsonResponse:
        self._ensure_search_dependencies()
        tilejson = self._fetch_tilejson(
            request.collection,
            request.item_id,
            request.bands,
        )
        tiles = tilejson.get("tiles") or []
        if not isinstance(tiles, list) or not tiles:
            raise RuntimeError(f"MPC tilejson did not include tiles for {request.item_id}.")
        bounds = tilejson.get("bounds")
        return TilejsonResponse(
            provider=self.provider_id,
            collection=request.collection,
            item_id=request.item_id,
            tiles=[str(tile) for tile in tiles],
            tilejson=tilejson,
            bounds=[float(value) for value in bounds] if isinstance(bounds, list) else None,
            minzoom=_optional_int(tilejson.get("minzoom")),
            maxzoom=_optional_int(tilejson.get("maxzoom")),
        )

    def get_cog_resolutions(
        self,
        collection: str,
        item_id: str,
        bands: List[str],
    ) -> Dict[str, Any]:
        self._ensure_search_dependencies()
        import planetary_computer  # type: ignore

        items = self._search_by_id(collection, item_id)
        if not items:
            raise RuntimeError(
                f"Item not found in provider '{self.provider_id}': {collection}/{item_id}"
            )
        item = planetary_computer.sign(items[0])
        properties = getattr(item, "properties", {}) or {}
        source_epsg = _source_epsg(properties)
        source_transform_values = properties.get("proj:transform")
        if not source_epsg or not source_transform_values:
            raise RuntimeError(
                "MPC item is missing proj:epsg/proj:code or proj:transform metadata."
            )
        base_transform = _source_affine([float(value) for value in source_transform_values])
        asset_key = bands[0] if bands else "red"
        asset = item.assets.get(asset_key)
        if asset is None:
            raise RuntimeError(f"Missing asset on item {item_id}: {asset_key}")

        metadata_levels = _read_cog_metadata_levels(asset.href)
        base_metadata = metadata_levels[0]
        resolutions = []
        for metadata in metadata_levels:
            transform = _cog_level_transform(base_transform, base_metadata, metadata)
            resolutions.append(
                {
                    "overview_index": metadata.overview_index,
                    "decimation": _cog_decimation(base_metadata, metadata),
                    "resolution_meters": _resolution_meters(transform),
                    "width": metadata.image_width,
                    "height": metadata.image_height,
                }
            )
        return {
            "provider": self.provider_id,
            "collection": collection,
            "item_id": item_id,
            "asset_key": asset_key,
            "resolutions": resolutions,
        }

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


def _optional_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _datetime_to_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _looks_like_output_write_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "permission denied" in message
        or "attempt to create new tiff file" in message
        or "no space left" in message
    )


def _source_epsg(properties: Dict[str, Any]) -> Optional[int]:
    epsg = properties.get("proj:epsg")
    if epsg:
        return int(epsg)
    code = properties.get("proj:code")
    if isinstance(code, str) and code.upper().startswith("EPSG:"):
        return int(code.split(":", 1)[1])
    return None


@dataclass(frozen=True)
class CogMetadata:
    byte_order: str
    overview_index: int
    ifd_offset: int
    image_width: int
    image_height: int
    bits_per_sample: int
    compression: int
    predictor: int
    sample_format: int
    samples_per_pixel: int
    tile_width: int
    tile_height: int
    tile_offsets: List[int]
    tile_bytecounts: List[int]


def _source_affine(values: List[float]) -> Any:
    from rasterio.transform import Affine  # type: ignore

    return Affine(
        values[0],
        values[1],
        values[2],
        values[3],
        values[4],
        values[5],
    )


def _cog_level_transform(base_transform: Any, base_metadata: CogMetadata, metadata: CogMetadata) -> Any:
    from rasterio.transform import Affine  # type: ignore

    return base_transform * Affine.scale(
        base_metadata.image_width / metadata.image_width,
        base_metadata.image_height / metadata.image_height,
    )


def _resolution_meters(transform: Any) -> float:
    x_resolution = math.hypot(transform.a, transform.d)
    y_resolution = math.hypot(transform.b, transform.e)
    return max(x_resolution, y_resolution)


def _cog_decimation(base_metadata: CogMetadata, metadata: CogMetadata) -> float:
    x_decimation = base_metadata.image_width / metadata.image_width
    y_decimation = base_metadata.image_height / metadata.image_height
    return (x_decimation + y_decimation) / 2.0


def _select_cog_level(
    *,
    metadata_levels: List[CogMetadata],
    base_transform: Any,
    target_resolution: Optional[float],
    requested_overview_index: Optional[int],
    asset_key: str,
) -> CogMetadata:
    if not metadata_levels:
        raise RuntimeError(f"Asset {asset_key} does not expose COG metadata levels.")
    if requested_overview_index is not None:
        if requested_overview_index < 0 or requested_overview_index >= len(metadata_levels):
            raise RuntimeError(
                f"Asset {asset_key} has {len(metadata_levels)} COG resolution level(s); "
                f"overview_index={requested_overview_index} is unavailable."
            )
        return metadata_levels[requested_overview_index]
    if target_resolution is None:
        return metadata_levels[0]

    base_metadata = metadata_levels[0]
    return min(
        metadata_levels,
        key=lambda metadata: abs(
            _resolution_meters(_cog_level_transform(base_transform, base_metadata, metadata))
            - target_resolution
        ),
    )


def _ensure_supported_cog(metadata: CogMetadata, asset_key: str) -> None:
    if metadata.compression != 8:
        raise RuntimeError(
            f"Asset {asset_key} uses unsupported TIFF compression: {metadata.compression}"
        )
    if metadata.bits_per_sample != 16 or metadata.sample_format != 1:
        raise RuntimeError(
            f"Asset {asset_key} uses unsupported sample type: "
            f"bits={metadata.bits_per_sample}, sample_format={metadata.sample_format}"
        )
    if metadata.samples_per_pixel != 1:
        raise RuntimeError(f"Asset {asset_key} is not a single-band COG.")
    if metadata.predictor not in {1, 2}:
        raise RuntimeError(
            f"Asset {asset_key} uses unsupported TIFF predictor: {metadata.predictor}"
        )


def _cog_window_tile_count(
    metadata: CogMetadata,
    row_start: int,
    row_stop: int,
    col_start: int,
    col_stop: int,
) -> int:
    tile_x_start = col_start // metadata.tile_width
    tile_x_stop = (col_stop - 1) // metadata.tile_width
    tile_y_start = row_start // metadata.tile_height
    tile_y_stop = (row_stop - 1) // metadata.tile_height
    return (tile_x_stop - tile_x_start + 1) * (tile_y_stop - tile_y_start + 1)


def _read_cog_window(
    asset_href: str,
    metadata: CogMetadata,
    row_start: int,
    row_stop: int,
    col_start: int,
    col_stop: int,
) -> Any:
    import numpy as np  # type: ignore

    output = np.zeros((row_stop - row_start, col_stop - col_start), dtype=_numpy_dtype(metadata))
    tiles_across = math.ceil(metadata.image_width / metadata.tile_width)
    tile_x_start = col_start // metadata.tile_width
    tile_x_stop = (col_stop - 1) // metadata.tile_width
    tile_y_start = row_start // metadata.tile_height
    tile_y_stop = (row_stop - 1) // metadata.tile_height

    for tile_y in range(tile_y_start, tile_y_stop + 1):
        for tile_x in range(tile_x_start, tile_x_stop + 1):
            tile_index = tile_y * tiles_across + tile_x
            tile = _read_cog_tile(asset_href, metadata, tile_index)

            tile_row_start = tile_y * metadata.tile_height
            tile_col_start = tile_x * metadata.tile_width
            src_row0 = max(row_start, tile_row_start)
            src_row1 = min(row_stop, tile_row_start + metadata.tile_height)
            src_col0 = max(col_start, tile_col_start)
            src_col1 = min(col_stop, tile_col_start + metadata.tile_width)

            output[
                src_row0 - row_start : src_row1 - row_start,
                src_col0 - col_start : src_col1 - col_start,
            ] = tile[
                src_row0 - tile_row_start : src_row1 - tile_row_start,
                src_col0 - tile_col_start : src_col1 - tile_col_start,
            ]
    return output


def _read_cog_tile(asset_href: str, metadata: CogMetadata, tile_index: int) -> Any:
    import numpy as np  # type: ignore

    if tile_index >= len(metadata.tile_offsets) or tile_index >= len(metadata.tile_bytecounts):
        raise RuntimeError(f"COG tile index out of bounds: {tile_index}")
    offset = metadata.tile_offsets[tile_index]
    bytecount = metadata.tile_bytecounts[tile_index]
    compressed = _http_range(asset_href, offset, offset + bytecount - 1)
    try:
        raw = zlib.decompress(compressed)
    except zlib.error:
        raw = zlib.decompress(compressed, -15)

    dtype = _numpy_dtype(metadata)
    expected_values = metadata.tile_width * metadata.tile_height
    tile = np.frombuffer(raw, dtype=dtype, count=expected_values)
    if tile.size != expected_values:
        raise RuntimeError(
            f"COG tile {tile_index} returned {tile.size} values; expected {expected_values}."
        )
    tile = tile.reshape((metadata.tile_height, metadata.tile_width)).copy()
    if metadata.predictor == 2:
        tile = np.cumsum(tile, axis=1, dtype=np.uint32).astype(dtype)
    return tile


def _numpy_dtype(metadata: CogMetadata) -> Any:
    import numpy as np  # type: ignore

    if metadata.bits_per_sample == 16 and metadata.sample_format == 1:
        return np.dtype(f"{metadata.byte_order}u2")
    raise RuntimeError("Unsupported COG numeric dtype.")


def _read_bytes_from_head_or_range(
    asset_href: str,
    head: bytes,
    offset: int,
    length: int,
) -> bytes:
    if offset + length <= len(head):
        return head[offset : offset + length]
    return _http_range(asset_href, offset, offset + length - 1)


def _read_cog_metadata_levels(asset_href: str) -> List[CogMetadata]:
    head = _http_range(asset_href, 0, 65535)
    if head[:2] == b"II":
        byte_order = "<"
    elif head[:2] == b"MM":
        byte_order = ">"
    else:
        raise RuntimeError("Asset is not a TIFF/COG file.")

    magic = struct.unpack(byte_order + "H", head[2:4])[0]
    if magic != 42:
        raise RuntimeError(f"Unsupported TIFF magic: {magic}")

    ifd_offset = struct.unpack(byte_order + "I", head[4:8])[0]
    metadata_levels: List[CogMetadata] = []
    seen_offsets: set[int] = set()
    while ifd_offset:
        if ifd_offset in seen_offsets:
            raise RuntimeError("TIFF IFD chain contains a loop.")
        seen_offsets.add(ifd_offset)
        tags, next_ifd_offset = _read_tiff_ifd(asset_href, head, byte_order, ifd_offset)

        def read_tag_values(tag_id: int, default: Optional[List[int]] = None) -> List[int]:
            tag = tags.get(tag_id)
            if tag is None:
                if default is not None:
                    return default
                raise RuntimeError(f"COG is missing TIFF tag {tag_id}.")
            type_id, count, value = tag
            type_size = {3: 2, 4: 4}.get(type_id)
            if type_size is None:
                raise RuntimeError(f"Unsupported TIFF tag type {type_id}.")
            total_size = type_size * count
            if total_size <= 4:
                raw = struct.pack(byte_order + "I", value)[:total_size]
            else:
                raw = _read_bytes_from_head_or_range(asset_href, head, value, total_size)
            fmt = "H" if type_id == 3 else "I"
            return list(struct.unpack(byte_order + fmt * count, raw))

        metadata_levels.append(
            CogMetadata(
                byte_order=byte_order,
                overview_index=len(metadata_levels),
                ifd_offset=ifd_offset,
                image_width=read_tag_values(256)[0],
                image_height=read_tag_values(257)[0],
                bits_per_sample=read_tag_values(258)[0],
                compression=read_tag_values(259)[0],
                predictor=read_tag_values(317, [1])[0],
                sample_format=read_tag_values(339, [1])[0],
                samples_per_pixel=read_tag_values(277, [1])[0],
                tile_width=read_tag_values(322)[0],
                tile_height=read_tag_values(323)[0],
                tile_offsets=read_tag_values(324),
                tile_bytecounts=read_tag_values(325),
            )
        )
        ifd_offset = next_ifd_offset

    if not metadata_levels:
        raise RuntimeError("COG does not contain any TIFF IFD levels.")
    return metadata_levels


def _read_tiff_ifd(
    asset_href: str,
    head: bytes,
    byte_order: str,
    ifd_offset: int,
) -> tuple[Dict[int, tuple[int, int, int]], int]:
    tag_count_raw = _read_bytes_from_head_or_range(asset_href, head, ifd_offset, 2)
    tag_count = struct.unpack(byte_order + "H", tag_count_raw)[0]
    directory_length = 2 + tag_count * 12 + 4
    directory = _read_bytes_from_head_or_range(asset_href, head, ifd_offset, directory_length)

    tags: Dict[int, tuple[int, int, int]] = {}
    cursor = 2
    for _ in range(tag_count):
        tag, type_id, count, value = struct.unpack(
            byte_order + "HHII",
            directory[cursor : cursor + 12],
        )
        tags[tag] = (type_id, count, value)
        cursor += 12

    next_ifd_offset = struct.unpack(byte_order + "I", directory[cursor : cursor + 4])[0]
    return tags, next_ifd_offset


def _http_range(asset_href: str, start: int, end: int) -> bytes:
    if end < start:
        return b""
    import requests

    expected = end - start + 1
    try:
        with requests.get(
            asset_href,
            headers={"Range": f"bytes={start}-{end}"},
            stream=True,
            timeout=(10, 120),
        ) as response:
            response.raise_for_status()
            chunks = []
            total = 0
            for chunk in response.iter_content(chunk_size=_COG_RANGE_CHUNK_BYTES):
                if not chunk:
                    continue
                chunks.append(chunk)
                total += len(chunk)
                if total > expected:
                    break
    except requests.RequestException as error:
        raise RuntimeError(f"Could not read COG byte range: {error}") from error

    content = b"".join(chunks)
    if len(content) != expected:
        raise RuntimeError(
            f"COG byte range returned {len(content)} bytes; expected {expected}. "
            "The remote server may not support HTTP Range reads."
        )
    return content


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
