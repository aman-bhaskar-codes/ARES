"""Shared session/workspace revalidation for long-lived event streams."""

from collections.abc import Callable

from ares.api.settings import Settings
from ares.application.auth import AuthStore
from ares.application.identity import Principal


def stream_revalidator(
    cfg: Settings, auth_store: AuthStore, principal: Principal | None, session_token: str
) -> Callable[[], bool]:
    def revalidate() -> bool:
        if cfg.auth_mode == "disabled":
            return True
        if principal is None or not session_token:
            return False
        resolved = auth_store.resolve_session(session_token)
        return bool(
            resolved is not None
            and resolved.principal.session_id == principal.session_id
            and resolved.principal.user_id == principal.user_id
            and resolved.principal.workspace_id == principal.workspace_id
        )

    return revalidate
