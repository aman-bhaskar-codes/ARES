# ruff: noqa: F403, F405, E501
from fastapi import APIRouter, Request, Response, HTTPException
from ares.api.dependencies import *
from ares.domain.models import *
from ares.domain.assets import *
from ares.domain.visualizations import *
from ares.application.auth import AuthenticationError
from ares.application.identity import Principal
import logging
logger = logging.getLogger('ares.api')
router = APIRouter()

@router.get('/api/v1/auth/me', response_model=AuthMeView)
def auth_me(request: Request) -> AuthMeView:
    cfg = request.app.state.settings
    getattr(request.app.state, 'auth_store', None)
    getattr(request.app.state, 'oidc', None)
    getattr(request.app.state, 'asset_admission', None)
    getattr(request.app.state, 'documents', None)
    getattr(request.app.state, 'exports', None)
    getattr(request.app.state, 'visualizations', None)
    getattr(request.app.state, 'db_engine', None)
    getattr(request.app.state, 'local_media_runtime', None)
    principal: Principal = request.state.principal
    return AuthMeView(user_id=principal.user_id, workspace_id=principal.workspace_id, role=principal.role.value, subject=principal.subject, email=principal.email, display_name=principal.display_name, auth_mode=cfg.auth_mode, csrf_required=cfg.auth_mode == 'oidc')

@router.get('/api/v1/workspaces', response_model=list[WorkspaceView])
def list_workspaces(request: Request) -> list[WorkspaceView]:
    cfg = request.app.state.settings
    auth_store = getattr(request.app.state, 'auth_store', None)
    getattr(request.app.state, 'oidc', None)
    getattr(request.app.state, 'asset_admission', None)
    getattr(request.app.state, 'documents', None)
    getattr(request.app.state, 'exports', None)
    getattr(request.app.state, 'visualizations', None)
    getattr(request.app.state, 'db_engine', None)
    getattr(request.app.state, 'local_media_runtime', None)
    principal: Principal = request.state.principal
    if cfg.auth_mode == 'disabled':
        return [WorkspaceView(id=principal.workspace_id, name='Local workspace', role=principal.role.value)]
    return [WorkspaceView.model_validate(item) for item in auth_store.list_workspaces(principal)]

@router.post('/api/v1/auth/workspace', response_model=AuthMeView)
def switch_workspace(payload: WorkspaceSwitchRequest, request: Request) -> AuthMeView:
    cfg = request.app.state.settings
    auth_store = getattr(request.app.state, 'auth_store', None)
    getattr(request.app.state, 'oidc', None)
    getattr(request.app.state, 'asset_admission', None)
    getattr(request.app.state, 'documents', None)
    getattr(request.app.state, 'exports', None)
    getattr(request.app.state, 'visualizations', None)
    getattr(request.app.state, 'db_engine', None)
    getattr(request.app.state, 'local_media_runtime', None)
    principal: Principal = request.state.principal
    if cfg.auth_mode == 'disabled':
        raise HTTPException(status_code=409, detail={'code': 'AUTH_DISABLED', 'message': 'local mode has one workspace'})
    try:
        updated = auth_store.switch_workspace(principal, payload.workspace_id)
    except AuthenticationError as exc:
        raise HTTPException(status_code=404, detail={'code': 'WORKSPACE_NOT_FOUND', 'message': str(exc)}) from exc
    return AuthMeView(user_id=updated.user_id, workspace_id=updated.workspace_id, role=updated.role.value, subject=updated.subject, email=updated.email, display_name=updated.display_name, auth_mode=cfg.auth_mode, csrf_required=True)

@router.post('/api/v1/auth/logout', status_code=204)
def auth_logout(request: Request) -> Response:
    cfg = request.app.state.settings
    auth_store = getattr(request.app.state, 'auth_store', None)
    getattr(request.app.state, 'oidc', None)
    getattr(request.app.state, 'asset_admission', None)
    getattr(request.app.state, 'documents', None)
    getattr(request.app.state, 'exports', None)
    getattr(request.app.state, 'visualizations', None)
    getattr(request.app.state, 'db_engine', None)
    getattr(request.app.state, 'local_media_runtime', None)
    principal: Principal = request.state.principal
    if cfg.auth_mode == 'oidc':
        auth_store.revoke_session(principal)
    response = Response(status_code=204)
    response.delete_cookie(cfg.session_cookie_name, path='/')
    response.delete_cookie(cfg.csrf_cookie_name, path='/')
    return response