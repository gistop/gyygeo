# gyygeo-carto-engine

Windows cartography engine for gyygeo.

## Purpose

This service keeps ArcPy on the Windows backend and exposes a small HTTP API for map rendering jobs. Web, desktop, mobile, and customer preview clients should call this service through controlled APIs instead of invoking ArcPy directly.

ArcPy rendering is executed in a worker subprocess. The API process does not import ArcPy directly, so a failed ArcPy import or render job does not crash the HTTP service.

## Runtime

- Windows
- ArcGIS Pro installed and licensed
- Dedicated `gyygeo-carto-py3` Python environment cloned from ArcGIS Pro Python
- FastAPI and Uvicorn installed in the Python environment that runs the service

## Python Environment

Do not install project dependencies into the original ArcGIS Pro `arcgispro-py3` environment.

Create a dedicated project environment:

```powershell
.\scripts\create-env.ps1
```

If environment creation is interrupted and leaves a partial folder, reset it and create it again:

```powershell
.\scripts\reset-env.ps1
.\scripts\create-env.ps1
```

The default project environment is:

```text
%LOCALAPPDATA%\ESRI\conda\envs\gyygeo-carto-py3
```

## Development Start

From `apps/carto-engine`:

```powershell
.\scripts\run-dev.ps1
```

This project should use the dedicated `gyygeo-carto-py3` environment. Do not rely on the bare `python` command on Windows machines where old Python versions may be installed.

## Install API Dependencies

FastAPI dependencies must be available in the same Python environment that can import ArcPy:

```powershell
.\scripts\install-deps.ps1
```

Then verify the runtime:

```powershell
.\scripts\check-runtime.ps1
```

## Core Endpoints

- `GET /health`
- `GET /runtime`
- `POST /api/v1/render/preview`
- `GET /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`

## First Render Flow

1. Put an ArcGIS Pro project template at `templates/aprx/default.aprx`.
2. Submit a render job to `POST /api/v1/render/preview`.
3. Poll `GET /api/v1/jobs/{job_id}` until the status is `done` or `failed`.
4. Read output paths from the job result.

The bundled/default template currently uses a layout named `布局`. Requests that specify
`layout_name` must match the actual ArcGIS Pro layout name exactly. A working GeoTIFF render request
is documented in `docs/engine-api.md`.

## Dry Run

Set `dry_run` to `true` in a render request to validate API, job storage, and output folder creation without importing ArcPy.
