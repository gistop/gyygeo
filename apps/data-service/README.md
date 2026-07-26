# gyygeo-data-service

Data acquisition and render-ready raster preparation service for gyygeo.

## Purpose

This service owns external data providers, dataset discovery, raster preparation, local cache paths,
and dataset records. The cartography engine should receive prepared local datasets or dataset IDs
instead of knowing how to talk to Microsoft Planetary Computer, Element84, or any later provider.

The first provider is Microsoft Planetary Computer. The provider architecture is intentionally
pluggable so Element84 or other STAC sources can be added without changing the REST API shape.

## Runtime

- Windows
- ArcGIS Pro installed, for the bundled conda command
- Dedicated `gyygeo-data-py3` Python environment
- FastAPI and Uvicorn
- Optional geospatial provider dependencies for real MPC work:
  - `pystac-client`
  - `planetary-computer`
  - `rasterio`
  - `numpy`

The API can start without provider dependencies. Provider endpoints will report missing
dependencies and provider operations will return a `503` or failed job with the missing packages.

Real MPC raster preparation requires the running GDAL/rasterio build to support remote HTTPS COG
reads. The service does not default to full-scene downloads; if remote COG reads fail in an
environment, fix the geospatial runtime or add an explicit cache/download policy.

## Python Environment

Use a separate project environment from `carto-engine` so raster/GDAL provider dependencies do not
affect ArcPy rendering:

```text
%LOCALAPPDATA%\ESRI\conda\envs\gyygeo-data-py3
```

Do not install dependencies into the original ArcGIS Pro `arcgispro-py3` environment, and do not
rely on the bare `python` command on Windows.

Create the environment if it does not already exist:

```powershell
.\scripts\create-env.ps1
```

Install service dependencies into the environment:

```powershell
.\scripts\install-deps.ps1
```

Verify the runtime:

```powershell
.\scripts\check-runtime.ps1
```

## Development Start

From `apps/data-service`:

```powershell
.\scripts\run-dev.ps1
```

## Core Endpoints

- `GET /health`
- `GET /runtime`
- `GET /api/v1/providers`
- `GET /api/v1/providers/{provider_id}/collections`
- `POST /api/v1/searches`
- `POST /api/v1/download-jobs`
- `POST /api/v1/prepare-jobs`
- `GET /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/datasets`
- `GET /api/v1/datasets/{dataset_id}`

## First MPC Flow

1. Search a STAC collection such as `landsat-c2-l2`.
2. Pick an item and COG asset keys such as `red`, `green`, `blue`.
3. Optionally submit a download job for selected raw assets or previews.
4. Submit a prepare job with bbox, bbox CRS, target CRS, and target resolution.
5. Poll the job until it is `done`.
6. Pass the prepared dataset path or dataset ID to `carto-engine` for map rendering.

A verified `POST /api/v1/prepare-jobs` JSON body is documented in `docs/data-service-api.md`.
