from fastapi import Request
from sqlalchemy import inspect
from ares.application.repository import Repository
from ares.api.settings import Settings
from ares.adapters.filesystem_blob import FilesystemBlobStore
from ares.application.auth import AuthStore
from ares.application.documents import DocumentIngestService
from ares.application.asset_ingestion import AssetAdmissionService
from ares.application.exports import ExportService
from ares.application.visualizations import VisualizationService

def get_repository(request: Request) -> Repository:
    return request.app.state.repository

def get_settings(request: Request) -> Settings:
    return request.app.state.settings

def get_blobs(request: Request) -> FilesystemBlobStore:
    return request.app.state.blobs

def get_auth_store(request: Request) -> AuthStore:
    return request.app.state.auth_store

def get_oidc(request: Request):
    return request.app.state.oidc

def get_documents(request: Request) -> DocumentIngestService:
    return request.app.state.documents

def get_asset_admission(request: Request) -> AssetAdmissionService:
    return request.app.state.asset_admission

def get_exports(request: Request) -> ExportService:
    return request.app.state.exports

def get_visualizations(request: Request) -> VisualizationService:
    return request.app.state.visualizations

def get_db_engine(request: Request):
    return request.app.state.db_engine

def get_local_media_runtime(request: Request):
    return request.app.state.local_media_runtime


def visualization_storage_ready(cfg, engine) -> bool:
    if not cfg.visualizations_enabled:
        return False
    try:
        inspector = inspect(engine)
        return inspector.has_table("visualization_datasets") and inspector.has_table("visualizations")
    except Exception:
        return False
