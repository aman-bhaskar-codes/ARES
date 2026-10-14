from __future__ import annotations
from fastapi import Depends
from ares.application.auth import OidcClient
import httpx
import logging
from fastapi import HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from ares.api.dependencies import get_settings
from ares.api.settings import Settings
from ares.application.auth import AuthStore, AuthenticationError
from ares.application.identity import Principal
from fastapi import APIRouter
from ares.api.dependencies import get_auth_store
from ares.api.dependencies import get_oidc
from ares.domain.models import AuthMeView, WorkspaceSwitchRequest, WorkspaceView

logger = logging.getLogger("ares.api")
router = APIRouter()


@router.get("/api/v1/auth/me", response_model=AuthMeView)
def auth_me(request: Request, *, cfg: Settings = Depends(get_settings)) -> AuthMeView:
    principal: Principal = request.state.principal
    return AuthMeView(
        user_id=principal.user_id,
        workspace_id=principal.workspace_id,
        role=principal.role.value,
        subject=principal.subject,
        email=principal.email,
        display_name=principal.display_name,
        auth_mode=cfg.auth_mode,
        csrf_required=cfg.auth_mode == "oidc",
    )


@router.get("/api/v1/workspaces", response_model=list[WorkspaceView])
def list_workspaces(
    request: Request,
    *,
    auth_store: AuthStore = Depends(get_auth_store),
    cfg: Settings = Depends(get_settings),
) -> list[WorkspaceView]:
    principal: Principal = request.state.principal
    if cfg.auth_mode == "disabled":
        return [
            WorkspaceView(
                id=principal.workspace_id, name="Local workspace", role=principal.role.value
            )
        ]
    return [WorkspaceView.model_validate(item) for item in auth_store.list_workspaces(principal)]


@router.post("/api/v1/auth/workspace", response_model=AuthMeView)
def switch_workspace(
    payload: WorkspaceSwitchRequest,
    request: Request,
    *,
    auth_store: AuthStore = Depends(get_auth_store),
    cfg: Settings = Depends(get_settings),
) -> AuthMeView:
    principal: Principal = request.state.principal
    if cfg.auth_mode == "disabled":
        raise HTTPException(
            status_code=409,
            detail={"code": "AUTH_DISABLED", "message": "local mode has one workspace"},
        )
    try:
        updated = auth_store.switch_workspace(principal, payload.workspace_id)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "WORKSPACE_NOT_FOUND", "message": str(exc)}
        ) from exc
    return AuthMeView(
        user_id=updated.user_id,
        workspace_id=updated.workspace_id,
        role=updated.role.value,
        subject=updated.subject,
        email=updated.email,
        display_name=updated.display_name,
        auth_mode=cfg.auth_mode,
        csrf_required=True,
    )


@router.post("/api/v1/auth/logout", status_code=204)
def auth_logout(
    request: Request,
    *,
    auth_store: AuthStore = Depends(get_auth_store),
    cfg: Settings = Depends(get_settings),
) -> Response:
    principal: Principal = request.state.principal
    if cfg.auth_mode == "oidc":
        auth_store.revoke_session(principal)
    response = Response(status_code=204)
    response.delete_cookie(cfg.session_cookie_name, path="/")
    response.delete_cookie(cfg.csrf_cookie_name, path="/")
    return response


@router.get("/api/v1/auth/login")
async def auth_login(
    return_path: str = "/", *, oidc: OidcClient | None = Depends(get_oidc)
) -> RedirectResponse:
    if oidc is None:
        raise HTTPException(
            status_code=404, detail={"code": "AUTH_DISABLED", "message": "OIDC is disabled"}
        )
    try:
        url = await oidc.begin_login(return_path)
    except (AuthenticationError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=503, detail={"code": "OIDC_UNAVAILABLE", "message": str(exc)}
        ) from exc
    return RedirectResponse(url, status_code=302)


@router.get("/api/v1/auth/callback")
async def auth_callback(
    code: str,
    state: str,
    *,
    auth_store: AuthStore = Depends(get_auth_store),
    cfg: Settings = Depends(get_settings),
    oidc: OidcClient | None = Depends(get_oidc),
) -> RedirectResponse:
    if oidc is None:
        raise HTTPException(
            status_code=404, detail={"code": "AUTH_DISABLED", "message": "OIDC is disabled"}
        )
    try:
        result = await oidc.complete_login(code=code, state=state)
    except (AuthenticationError, httpx.HTTPError) as exc:
        auth_store.audit(None, "auth.login_failed", metadata={"reason": type(exc).__name__})
        raise HTTPException(
            status_code=401, detail={"code": "OIDC_LOGIN_FAILED", "message": str(exc)}
        ) from exc
    response = RedirectResponse(
        f"{cfg.frontend_origin.rstrip('/')}{result.return_path}", status_code=303
    )
    response.set_cookie(
        cfg.session_cookie_name,
        result.session_token,
        httponly=True,
        secure=cfg.session_cookie_secure,
        samesite="lax",
        path="/",
        max_age=cfg.session_ttl_hours * 3600,
    )
    response.set_cookie(
        cfg.csrf_cookie_name,
        result.csrf_token,
        httponly=False,
        secure=cfg.session_cookie_secure,
        samesite="lax",
        path="/",
        max_age=cfg.session_ttl_hours * 3600,
    )
    return response
