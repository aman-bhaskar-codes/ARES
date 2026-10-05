from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterator
from uuid import UUID


SYSTEM_USER_ID = UUID("00000000-0000-4000-8000-000000000001")
SYSTEM_WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000002")


class WorkspaceRole(StrEnum):
    VIEWER = "viewer"
    EDITOR = "editor"
    OWNER = "owner"

    def allows_write(self) -> bool:
        return self in {WorkspaceRole.EDITOR, WorkspaceRole.OWNER}


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: UUID
    workspace_id: UUID
    role: WorkspaceRole
    subject: str
    email: str | None = None
    display_name: str | None = None
    session_id: UUID | None = None

    @property
    def can_write(self) -> bool:
        return self.role.allows_write()


_current_principal: ContextVar[Principal | None] = ContextVar("ares_principal", default=None)


def current_principal() -> Principal | None:
    return _current_principal.get()


def require_principal() -> Principal:
    principal = current_principal()
    if principal is None:
        raise RuntimeError("tenant-aware operation requires an authenticated principal")
    return principal


@contextmanager
def principal_scope(principal: Principal) -> Iterator[None]:
    token: Token[Principal | None] = _current_principal.set(principal)
    try:
        yield
    finally:
        _current_principal.reset(token)


def local_principal() -> Principal:
    return Principal(
        user_id=SYSTEM_USER_ID,
        workspace_id=SYSTEM_WORKSPACE_ID,
        role=WorkspaceRole.OWNER,
        subject="local:system",
        email=None,
        display_name="Local ARES",
        session_id=None,
    )
