# gyygeo-carto-web-api

Application backend for the gyygeo carto web console.

## Purpose

This service owns web-application concerns that should not live in the browser or in the
domain services:

1. Keep AI provider API keys off the frontend.
2. Proxy the right-side AI chat panel to DeepSeek.
3. Carry current web page context into AI requests.
4. Provide a future home for auth, user sessions, chat history, and orchestration across
   `data-service` and `carto-engine`.

`data-service` should stay focused on provider search and raster preparation. `carto-engine`
should stay focused on rendering.

## Runtime

- Windows
- Dedicated `gyygeo-web-api-py3` Python environment
- FastAPI and Uvicorn
- DeepSeek API key for AI chat

## Configuration

Copy `.env.example` to `.env`, then set your DeepSeek key:

```powershell
Copy-Item .env.example .env
```

```env
DEEPSEEK_API_KEY=sk-...
```

Optional overrides:

```text
GYYGEO_WEB_API_PORT=8020
GYYGEO_WEB_API_DEEPSEEK_MODEL=deepseek-v4-flash
GYYGEO_WEB_API_DEEPSEEK_BASE_URL=https://api.deepseek.com
GYYGEO_WEB_API_DATA_SERVICE_URL=http://127.0.0.1:8010
GYYGEO_WEB_API_CARTO_ENGINE_URL=http://127.0.0.1:8000
```

## Python Environment

Create the environment if it does not already exist:

```powershell
.\scripts\create-env.ps1
```

Install service dependencies:

```powershell
.\scripts\install-deps.ps1
```

Verify the runtime:

```powershell
.\scripts\check-runtime.ps1
```

## Development Start

From `apps/carto-web-api`:

```powershell
.\scripts\run-dev.ps1
```

## Core Endpoints

- `GET /health`
- `GET /runtime`
- `POST /api/v1/ai/chat`
