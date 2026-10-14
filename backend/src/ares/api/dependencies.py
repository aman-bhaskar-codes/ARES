import logging
from collections.abc import Callable
from typing import cast

from fastapi import Request
from sqlalchemy import Engine, inspect

from ares.adapters.filesystem_blob import FilesystemBlobStore
from ares.adapters.pdf_parser import BoundedPdfParser
from ares.api.settings import Settings
from ares.application.asset_ingestion import AssetAdmissionService
from ares.application.auth import AuthStore, OidcClient
from ares.application.documents import DocumentIngestService
from ares.application.exports import ExportService
from ares.application.media_capabilities import LocalMediaRuntimeCapabilities
from ares.application.repository import Repository
from ares.application.visualizations import VisualizationService


def get_repository(request: Request) -> Repository:
    return cast(Repository, request.app.state.repository)


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_blobs(request: Request) -> FilesystemBlobStore:
    return cast(FilesystemBlobStore, request.app.state.blobs)


def get_auth_store(request: Request) -> AuthStore:
    return cast(AuthStore, request.app.state.auth_store)


def get_oidc(request: Request) -> OidcClient | None:
    return cast(OidcClient | None, request.app.state.oidc)


def get_documents(request: Request) -> DocumentIngestService:
    return cast(DocumentIngestService, request.app.state.documents)


def get_asset_admission(request: Request) -> AssetAdmissionService:
    return cast(AssetAdmissionService, request.app.state.asset_admission)


def get_exports(request: Request) -> ExportService:
    return cast(ExportService, request.app.state.exports)


def get_visualizations(request: Request) -> VisualizationService:
    return cast(VisualizationService, request.app.state.visualizations)


def get_db_engine(request: Request) -> Engine:
    return cast(Engine, request.app.state.db_engine)


def get_local_media_runtime(request: Request) -> Callable[[], LocalMediaRuntimeCapabilities]:
    return cast(Callable[[], LocalMediaRuntimeCapabilities], request.app.state.local_media_runtime)


def visualization_storage_ready(cfg: Settings, engine: Engine) -> bool:
    if not cfg.visualizations_enabled:
        return False
    try:
        inspector = inspect(engine)
        return inspector.has_table("visualization_datasets") and inspector.has_table(
            "visualizations"
        )
    except Exception as _boundary_error:
        logging.getLogger(__name__).warning("dependencies: recovery boundary (%s)", type(_boundary_error).__name__)
        return False


def get_pdf_parser(request: Request) -> BoundedPdfParser:
    return cast(BoundedPdfParser, request.app.state.pdf_parser)
