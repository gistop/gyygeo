# data-service API

Base URL for local development:

```text
http://127.0.0.1:8010
```

## Health

```http
GET /health
```

Returns service status without contacting providers.

## Runtime Environment

`data-service` is expected to run in its own project Python environment:

```text
%LOCALAPPDATA%\ESRI\conda\envs\gyygeo-data-py3
```

Use `apps/data-service/scripts/check-runtime.ps1` to verify FastAPI dependencies and MPC provider
dependencies in that environment.

## Runtime

```http
GET /runtime
```

Returns provider status, including missing optional dependencies.

## Providers

```http
GET /api/v1/providers
GET /api/v1/providers/{provider_id}
GET /api/v1/providers/{provider_id}/collections
```

The first provider is:

```text
mpc
```

Provider operations return `503` when required packages are missing from the running environment.

## Search Items

```http
POST /api/v1/searches
Content-Type: application/json
```

Example:

```json
{
  "provider": "mpc",
  "collection": "landsat-c2-l2",
  "bbox": [116.1, 39.7, 116.7, 40.2],
  "datetime": "2025-07-01/2025-07-31",
  "limit": 10,
  "cloud_cover_lte": 20
}
```

Search responses contain normalized item summaries and asset keys. Signed COG URLs are not exposed
by default; preparation jobs resolve and sign provider assets internally.

## Prepare Raster

```http
POST /api/v1/prepare-jobs
Content-Type: application/json
```

Example:

```json
{
  "provider": "mpc",
  "collection": "landsat-c2-l2",
  "item_id": "LC09_L2SP_123033_20250622_02_T1",
  "bbox": [116.1, 39.0, 116.7, 39.6],
  "bbox_crs": "EPSG:4326",
  "bands": ["red", "green", "blue"],
  "target_resolution": 120,
  "target_crs": "EPSG:3857",
  "output": {
    "format": "geotiff",
    "purpose": "carto-render"
  }
}
```

This example has been verified as a working `landsat-c2-l2` preparation request for local
development.

The service creates an async job and a dataset record. When the job is done, the result contains a
render-ready GeoTIFF path that can be passed to `carto-engine`.

## Download Assets

```http
POST /api/v1/download-jobs
Content-Type: application/json
```

Example:

```json
{
  "provider": "mpc",
  "collection": "landsat-c2-l2",
  "item_id": "LC08_L2SP_118039_20250627_02_T1",
  "assets": ["rendered_preview"]
}
```

For raw COG assets, use keys such as:

```json
{
  "provider": "mpc",
  "collection": "landsat-c2-l2",
  "item_id": "LC08_L2SP_118039_20250627_02_T1",
  "assets": ["red", "green", "blue"]
}
```

Download jobs are explicit because raw COG assets can be large. This path downloads selected full
assets into the local cache and records an `asset_bundle` dataset.

## Jobs

```http
GET /api/v1/jobs
GET /api/v1/jobs/{job_id}
```

Job statuses:

- `pending`
- `running`
- `done`
- `failed`

## Datasets

```http
GET /api/v1/datasets
GET /api/v1/datasets/{dataset_id}
```

Dataset statuses:

- `preparing`
- `ready`
- `failed`
- `expired`
