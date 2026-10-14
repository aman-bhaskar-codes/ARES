"""API factory: lifecycle/security bootstrap plus explicitly owned routers."""

from pathlib import Path
from fastapi import FastAPI
from ares.api.spa_static import SpaStaticFiles
from ares.api.bootstrap import create_application
from ares.api.settings import Settings
from ares.api.routers import (
    auth,
    system,
    conversations,
    assets,
    ingestions,
    segments,
    documents,
    runs,
    evidence,
    artifacts,
    internal,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    app = create_application(settings)
    for module in (
        auth,
        system,
        conversations,
        assets,
        ingestions,
        segments,
        documents,
        runs,
        evidence,
        artifacts,
        internal,
    ):
        app.include_router(module.router)
    cfg = app.state.settings
    if cfg.web_dist_dir and Path(cfg.web_dist_dir).is_dir():
        app.mount("/", SpaStaticFiles(directory=cfg.web_dist_dir, html=True), name="web")
    return app


app = create_app()
