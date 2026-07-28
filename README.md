# gyygeo

`gyygeo` is the workspace for GYY GIS and cartography services.

Implemented modules:

- `apps/carto-engine`: Windows cartography engine built with FastAPI and ArcPy.
- `apps/data-service`: Data acquisition and render-ready raster preparation service.
- `apps/carto-web`: Vite, React, TypeScript, MapLibre, and TanStack Query web console.
- `apps/carto-web-api`: Application backend and AI proxy for the web console.

## Development Start

Each app can still be started independently with its own local instructions. To start the full
development stack from the workspace root:

```powershell
.\scripts\run-all-dev.cmd
```

The script starts:

- `carto-engine`: http://127.0.0.1:8000
- `data-service`: http://127.0.0.1:8010
- `carto-web-api`: http://127.0.0.1:8020
- `carto-web`: http://127.0.0.1:5173

Logs and process state are written under `.run`. To stop the stack:

```powershell
.\scripts\stop-all-dev.cmd
```
