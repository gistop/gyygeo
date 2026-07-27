# gyygeo-carto-web

Web control console for the gyygeo cartography pipeline.

## Purpose

This app lets a browser call `data-service` and `carto-engine` through HTTP APIs:

1. Search provider items by bbox, date, and cloud cover.
2. Submit a raster preparation job to `data-service`.
3. Submit a preview render job to `carto-engine`.
4. Poll both services and show the output paths.

## Runtime

- Node.js 20 or newer
- `apps/carto-web-api` running at `http://127.0.0.1:8020`
- `apps/data-service` running at `http://127.0.0.1:8010`
- `apps/carto-engine` running at `http://127.0.0.1:8000`

## Configuration

Copy `.env.example` to `.env` if local service URLs differ:

```text
VITE_DATA_SERVICE_URL=http://127.0.0.1:8010
VITE_CARTO_WEB_API_URL=http://127.0.0.1:8020
VITE_CARTO_ENGINE_URL=http://127.0.0.1:8000
```

The right-side AI chat panel calls `carto-web-api` at `/api/v1/ai/chat`, which proxies to
DeepSeek with `deepseek-v4-flash`.

## Development Start

From `apps/carto-web`:

```powershell
npm install
npm run dev
```

Then open:

```text
http://127.0.0.1:5173/
```
