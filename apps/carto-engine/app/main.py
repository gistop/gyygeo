from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.health import router as health_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.render import router as render_router
from app.arcpy_engine.renderer import ArcPyRenderer
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.jobs.runner import JobRunner
from app.jobs.store import JobStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    settings.ensure_directories()

    store = JobStore(settings.database_path)
    store.initialize()

    renderer = ArcPyRenderer(settings)
    runner = JobRunner(
        store=store,
        renderer=renderer,
        output_root=settings.output_dir,
        max_workers=settings.max_workers,
    )

    app.state.settings = settings
    app.state.store = store
    app.state.runner = runner

    yield

    runner.shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="gyygeo-carto-engine",
        version="0.1.0",
        description="Windows ArcPy cartography engine for gyygeo.",
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
    app.include_router(jobs_router, prefix=settings.api_prefix)
    app.include_router(render_router, prefix=settings.api_prefix)
    return app


app = create_app()
