# gyygeo Architecture

## Current Scope

The first implementation scope is `apps/carto-engine`.

`carto-engine` is a Windows backend service. It owns ArcPy rendering, job execution, project template access, and output files. Browser, desktop, mobile, and customer preview clients should access it through HTTP APIs.

## Target Module Layout

```text
gyygeo/
  apps/
    carto-engine/
    carto-web/
    carto-desktop/
  packages/
    api-client/
    carto-schema/
  docs/
```

Only `apps/carto-engine` is implemented now.

## Engine Boundaries

- API layer: receives requests and returns job state.
- Job layer: records status and runs long tasks outside the request path.
- ArcPy layer: runs ArcPy inside a worker subprocess.
- Storage layer: manages runtime paths and output files.

## Production Notes

- Keep the original ArcGIS Pro `arcgispro-py3` environment clean. Clone it into a dedicated project environment named `gyygeo-py3`, then install service dependencies there.
- Run ArcPy jobs with a low concurrency value first. ArcGIS Pro licensing and ArcPy process behavior should determine the final concurrency model.
- Keep customer preview access separate from internal output paths.
- Store every render request as JSON so outputs can be audited and reproduced.
- Move from local SQLite and in-process jobs to a dedicated queue when multi-machine or high-concurrency rendering is needed.
