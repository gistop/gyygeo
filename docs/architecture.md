# gyygeo Architecture

## Current Scope

The first implementation scope was `apps/carto-engine`. The workspace now also includes
`apps/data-service` for data acquisition and render-ready raster preparation, `apps/carto-web`
for browser-based workflow control, and `apps/carto-web-api` for web-application backend
concerns.

`carto-engine` is a Windows backend service. It owns ArcPy rendering, job execution, project template access, and output files. Browser, desktop, mobile, and customer preview clients should access it through HTTP APIs.

`data-service` is a backend service. It owns external data provider access, dataset discovery,
COG/raster preparation, cache paths, and dataset records. `carto-engine` should consume prepared
datasets instead of talking directly to external providers.

`carto-web` is a browser client. It owns the interactive bbox/map UI, service health checks,
workflow forms, API calls, job polling, and output display. It should not import ArcPy or raster
provider libraries.

`carto-web-api` is the application backend for `carto-web`. It owns browser-adjacent server
concerns such as AI provider keys, AI chat proxying, future user sessions, authorization, chat
history, and orchestration across `data-service` and `carto-engine`.

## Target Module Layout

```text
gyygeo/
  apps/
    carto-engine/
    data-service/
    carto-web/
    carto-web-api/
    carto-desktop/
  packages/
    api-client/
    carto-schema/
  docs/
```

`apps/carto-engine`, `apps/data-service`, `apps/carto-web`, and `apps/carto-web-api` are
implemented now.

## Data Service Boundaries

- Provider layer: talks to external data sources such as Microsoft Planetary Computer.
- Search layer: normalizes STAC item and asset summaries.
- Prepare layer: reads COG assets by bbox and target resolution, then writes render-ready rasters.
- Job layer: records async preparation status.
- Dataset layer: records prepared dataset metadata and local cache paths.

## Engine Boundaries

- API layer: receives requests and returns job state.
- Job layer: records status and runs long tasks outside the request path.
- ArcPy layer: runs ArcPy inside a worker subprocess.
- Storage layer: manages runtime paths and output files.

## Web Boundaries

- Map layer: displays a MapLibre basemap and selected bbox.
- Form layer: collects provider, search, preparation, and render parameters.
- API layer: calls `carto-web-api`, `data-service`, and `carto-engine` through HTTP.
- Job layer: polls backend job records and displays terminal output paths.

## Web API Boundaries

- AI layer: proxies chat requests to DeepSeek while keeping API keys off the browser client.
- Context layer: receives current map, dataset, and job state from `carto-web`.
- Application layer: future home for auth, user sessions, chat history, and workflow
  orchestration across the domain services.
- Integration layer: calls `data-service` and `carto-engine` when the AI assistant needs tools.

## Production Notes

- Keep the original ArcGIS Pro `arcgispro-py3` environment clean. Use separate project environments: `gyygeo-carto-py3` for ArcPy rendering and `gyygeo-data-py3` for data provider/raster dependencies.
- Run ArcPy jobs with a low concurrency value first. ArcGIS Pro licensing and ArcPy process behavior should determine the final concurrency model.
- Keep customer preview access separate from internal output paths.
- Store every render request as JSON so outputs can be audited and reproduced.
- Move from local SQLite and in-process jobs to a dedicated queue when multi-machine or high-concurrency rendering is needed.
