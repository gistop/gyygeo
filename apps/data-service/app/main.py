from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.datasets import router as datasets_router
from app.api.routes.downloads import router as downloads_router
from app.api.routes.health import router as health_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.prepare import router as prepare_router
from app.api.routes.providers import router as providers_router
from app.api.routes.searches import router as searches_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.jobs.runner import PrepareJobRunner
from app.jobs.store import DataStore
from app.providers.mpc import MpcProvider
from app.providers.registry import ProviderRegistry


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    settings.ensure_directories()

    store = DataStore(settings.database_path)
    store.initialize()

    providers = ProviderRegistry([MpcProvider(settings.mpc_stac_url)])
    runner = PrepareJobRunner(
        store=store,
        providers=providers,
        output_root=settings.cache_dir,
        prepared_dir=settings.prepared_dir,
        max_workers=settings.max_workers,
    )

    app.state.settings = settings
    app.state.store = store
    app.state.providers = providers
    app.state.runner = runner

    yield

    runner.shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="gyygeo-data-service",
        version="0.1.0",
        description="Data acquisition and render-ready raster preparation service for gyygeo.",
        lifespan=lifespan,
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(health_router)
    app.include_router(providers_router, prefix=settings.api_prefix)
    app.include_router(searches_router, prefix=settings.api_prefix)
    app.include_router(downloads_router, prefix=settings.api_prefix)
    app.include_router(prepare_router, prefix=settings.api_prefix)
    app.include_router(jobs_router, prefix=settings.api_prefix)
    app.include_router(datasets_router, prefix=settings.api_prefix)
    return app


app = create_app()
