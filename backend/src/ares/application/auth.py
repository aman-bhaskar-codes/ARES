from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit
from uuid import UUID, uuid4

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ares.adapters.db import (
    AuditEventRow,
    OidcStateRow,
    SessionRow,
    UserRow,
    WorkspaceMembershipRow,
    WorkspaceRow,
)
from ares.application.identity import Principal, WorkspaceRole, principal_scope


class AuthenticationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PendingOidcState:
    code_verifier: str
    nonce: str
    return_path: str


@dataclass(frozen=True, slots=True)
class BrowserSession:
    principal: Principal
    csrf_hash: str


@dataclass(frozen=True, slots=True)
class LoginResult:
    session_token: str
    csrf_token: str
    return_path: str
    principal: Principal


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))




def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def safe_return_path(value: str | None) -> str:
    if not value:
        return "/"
    if "\\" in value or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return "/"
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return "/"
    path = parsed.path or "/"
    if parsed.query:
        path += f"?{parsed.query}"
    return path[:1024]


class AuthStore:
    def __init__(self, sessions: sessionmaker[Session]):
        self._sessions = sessions

    def create_oidc_state(self, *, state: str, verifier: str, nonce: str, return_path: str, ttl_seconds: int) -> None:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            session.add(
                OidcStateRow(
                    state_hash=_sha256(state),
                    code_verifier=verifier,
                    nonce=nonce,
                    return_path=safe_return_path(return_path),
                    expires_at=now + timedelta(seconds=ttl_seconds),
                    created_at=now,
                )
            )

    def consume_oidc_state(self, state: str) -> PendingOidcState:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            row = session.scalar(select(OidcStateRow).where(OidcStateRow.state_hash == _sha256(state)))
            if row is None or row.consumed_at is not None or _as_utc(row.expires_at) <= now:
                raise AuthenticationError("OIDC state is invalid, expired, or already consumed")
            row.consumed_at = now
            return PendingOidcState(row.code_verifier, row.nonce, row.return_path)

    def upsert_identity(self, *, subject: str, email: str | None, display_name: str | None) -> Principal:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            user = session.scalar(select(UserRow).where(UserRow.subject == subject))
            if user is None:
                user = UserRow(subject=subject, email=email, display_name=display_name, created_at=now, updated_at=now)
                session.add(user)
                session.flush()
                workspace = WorkspaceRow(name=(display_name or email or "ARES")[:120] + " workspace", created_at=now)
                session.add(workspace)
                session.flush()
                membership = WorkspaceMembershipRow(
                    workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.OWNER.value, created_at=now
                )
                session.add(membership)
            else:
                user.email = email or user.email
                user.display_name = display_name or user.display_name
                user.updated_at = now
                membership = session.scalar(
                    select(WorkspaceMembershipRow)
                    .where(WorkspaceMembershipRow.user_id == user.id)
                    .order_by(WorkspaceMembershipRow.created_at.asc())
                )
                if membership is None:
                    workspace = WorkspaceRow(name=(display_name or email or "ARES")[:120] + " workspace", created_at=now)
                    session.add(workspace)
                    session.flush()
                    membership = WorkspaceMembershipRow(
                        workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.OWNER.value, created_at=now
                    )
                    session.add(membership)
            session.flush()
            return Principal(
                user_id=user.id,
                workspace_id=membership.workspace_id,
                role=WorkspaceRole(membership.role),
                subject=user.subject,
                email=user.email,
                display_name=user.display_name,
            )

    def create_session(self, principal: Principal, *, token: str, csrf_token: str, ttl_hours: int) -> Principal:
        now = datetime.now(UTC)
        with principal_scope(principal):
            with self._sessions.begin() as session:
                row = SessionRow(
                    token_hash=_sha256(token),
                    csrf_hash=_sha256(csrf_token),
                    user_id=principal.user_id,
                    workspace_id=principal.workspace_id,
                    expires_at=now + timedelta(hours=ttl_hours),
                    created_at=now,
                )
                session.add(row)
                session.flush()
                self._audit_in_session(session, principal, "auth.login", "session", str(row.id), {})
                return Principal(
                    user_id=principal.user_id, workspace_id=principal.workspace_id, role=principal.role,
                    subject=principal.subject, email=principal.email, display_name=principal.display_name, session_id=row.id,
                )

    def resolve_session(self, token: str) -> BrowserSession | None:
        if not token:
            return None
        now = datetime.now(UTC)
        with self._sessions() as session:
            row = session.scalar(
                select(SessionRow).where(
                    SessionRow.token_hash == _sha256(token), SessionRow.revoked_at.is_(None), SessionRow.expires_at > now
                )
            )
            if row is None:
                return None
            user = session.get(UserRow, row.user_id)
            membership = session.scalar(
                select(WorkspaceMembershipRow).where(
                    WorkspaceMembershipRow.workspace_id == row.workspace_id,
                    WorkspaceMembershipRow.user_id == row.user_id,
                )
            )
            if user is None or membership is None:
                return None
            return BrowserSession(
                principal=Principal(
                    user_id=user.id, workspace_id=row.workspace_id, role=WorkspaceRole(membership.role),
                    subject=user.subject, email=user.email, display_name=user.display_name, session_id=row.id,
                ),
                csrf_hash=row.csrf_hash,
            )

    def revoke_session(self, principal: Principal) -> None:
        if principal.session_id is None:
            return
        with self._sessions.begin() as session:
            row = session.get(SessionRow, principal.session_id)
            if row is not None and row.user_id == principal.user_id:
                row.revoked_at = datetime.now(UTC)
                self._audit_in_session(session, principal, "auth.logout", "session", str(row.id), {})

    def list_workspaces(self, principal: Principal) -> list[dict[str, str]]:
        with self._sessions() as session:
            rows = session.execute(
                select(WorkspaceRow, WorkspaceMembershipRow.role)
                .join(WorkspaceMembershipRow, WorkspaceMembershipRow.workspace_id == WorkspaceRow.id)
                .where(WorkspaceMembershipRow.user_id == principal.user_id)
                .order_by(WorkspaceRow.created_at.asc())
            ).all()
            return [{"id": str(workspace.id), "name": workspace.name, "role": role} for workspace, role in rows]

    def switch_workspace(self, principal: Principal, workspace_id: UUID) -> Principal:
        if principal.session_id is None:
            raise AuthenticationError("workspace switching requires a browser session")
        with self._sessions.begin() as session:
            membership = session.scalar(
                select(WorkspaceMembershipRow).where(
                    WorkspaceMembershipRow.workspace_id == workspace_id,
                    WorkspaceMembershipRow.user_id == principal.user_id,
                )
            )
            if membership is None:
                raise AuthenticationError("workspace membership not found")
            row = session.get(SessionRow, principal.session_id)
            if row is None or row.revoked_at is not None:
                raise AuthenticationError("session not found")
            row.workspace_id = workspace_id
            updated = Principal(
                user_id=principal.user_id, workspace_id=workspace_id, role=WorkspaceRole(membership.role),
                subject=principal.subject, email=principal.email, display_name=principal.display_name,
                session_id=principal.session_id,
            )
            self._audit_in_session(session, updated, "workspace.switch", "workspace", str(workspace_id), {})
            return updated

    def audit(
        self, principal: Principal | None, action: str, target_type: str | None = None,
        target_id: str | None = None, metadata: dict[str, object] | None = None,
    ) -> None:
        with self._sessions.begin() as session:
            self._audit_in_session(session, principal, action, target_type, target_id, metadata or {})

    @staticmethod
    def _audit_in_session(
        session: Session, principal: Principal | None, action: str, target_type: str | None,
        target_id: str | None, metadata: dict[str, object],
    ) -> None:
        safe: dict[str, object] = {}
        for key, value in list(metadata.items())[:16]:
            if key.lower() in {"token", "authorization", "cookie", "secret", "password", "code", "verifier"}:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                safe[str(key)[:64]] = value[:256] if isinstance(value, str) else value
        session.add(
            AuditEventRow(
                workspace_id=principal.workspace_id if principal else None,
                user_id=principal.user_id if principal else None,
                action=action[:96], target_type=(target_type or None), target_id=(target_id or None),
                metadata_json=safe, created_at=datetime.now(UTC),
            )
        )


class OidcClient:
    def __init__(
        self, *, issuer: str, client_id: str, client_secret: str, redirect_uri: str,
        scopes: str, state_ttl_seconds: int, session_ttl_hours: int, store: AuthStore,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.issuer = issuer.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes
        self.state_ttl_seconds = state_ttl_seconds
        self.session_ttl_hours = session_ttl_hours
        self.store = store
        self.http = http or httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=False)
        self._owns_http = http is None
        self._discovery: tuple[float, dict[str, Any]] | None = None
        self._jwks: tuple[float, dict[str, Any]] | None = None

    async def close(self) -> None:
        if self._owns_http:
            await self.http.aclose()

    async def begin_login(self, return_path: str = "/") -> str:
        metadata = await self._get_discovery()
        methods = metadata.get("code_challenge_methods_supported")
        if isinstance(methods, list) and methods and "S256" not in methods:
            raise AuthenticationError("OIDC provider does not advertise PKCE S256 support")
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        nonce = secrets.token_urlsafe(32)
        challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
        self.store.create_oidc_state(
            state=state, verifier=verifier, nonce=nonce, return_path=safe_return_path(return_path),
            ttl_seconds=self.state_ttl_seconds,
        )
        params = {
            "response_type": "code", "client_id": self.client_id, "redirect_uri": self.redirect_uri,
            "scope": self.scopes, "state": state, "nonce": nonce,
            "code_challenge": challenge, "code_challenge_method": "S256",
        }
        return f"{metadata['authorization_endpoint']}?{urlencode(params)}"

    async def complete_login(self, *, code: str, state: str) -> LoginResult:
        pending = self.store.consume_oidc_state(state)
        metadata = await self._get_discovery()
        form = {
            "grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri,
            "client_id": self.client_id, "code_verifier": pending.code_verifier,
        }
        if self.client_secret:
            form["client_secret"] = self.client_secret
        response = await self.http.post(metadata["token_endpoint"], data=form, headers={"Accept": "application/json"})
        if response.status_code >= 400:
            raise AuthenticationError("OIDC token exchange failed")
        tokens = response.json()
        id_token = tokens.get("id_token")
        if not isinstance(id_token, str):
            raise AuthenticationError("OIDC provider did not return an ID token")
        claims = await self._verify_id_token(id_token, expected_nonce=pending.nonce, metadata=metadata)
        access_token = tokens.get("access_token")
        if metadata.get("userinfo_endpoint") and isinstance(access_token, str):
            userinfo = await self.http.get(
                metadata["userinfo_endpoint"], headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
            )
            if userinfo.status_code >= 400:
                raise AuthenticationError("OIDC UserInfo request failed")
            info = userinfo.json()
            if info.get("sub") != claims.get("sub"):
                raise AuthenticationError("OIDC UserInfo subject does not match the validated ID token")
            claims = {**claims, **{k: v for k, v in info.items() if k in {"email", "name", "preferred_username"}}}
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise AuthenticationError("OIDC ID token has no subject")
        subject_key = f"{self.issuer}|{subject}"
        if len(subject_key) > 512:
            raise AuthenticationError("OIDC subject identifier exceeds ARES storage limits")
        principal = self.store.upsert_identity(
            subject=subject_key,
            email=claims.get("email") if isinstance(claims.get("email"), str) else None,
            display_name=(claims.get("name") or claims.get("preferred_username"))
            if isinstance(claims.get("name") or claims.get("preferred_username"), str) else None,
        )
        session_token = secrets.token_urlsafe(48)
        csrf_token = secrets.token_urlsafe(32)
        principal = self.store.create_session(
            principal, token=session_token, csrf_token=csrf_token, ttl_hours=self.session_ttl_hours
        )
        return LoginResult(session_token, csrf_token, pending.return_path, principal)

    async def _get_discovery(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._discovery and self._discovery[0] > now:
            return self._discovery[1]
        response = await self.http.get(f"{self.issuer}/.well-known/openid-configuration", headers={"Accept": "application/json"})
        response.raise_for_status()
        data = response.json()
        if data.get("issuer") != self.issuer:
            raise AuthenticationError("OIDC discovery issuer mismatch")
        required = {"authorization_endpoint", "token_endpoint", "jwks_uri"}
        if not required.issubset(data):
            raise AuthenticationError("OIDC discovery document is incomplete")
        if self.issuer.startswith("https://"):
            endpoint_names = ["authorization_endpoint", "token_endpoint", "jwks_uri"]
            if data.get("userinfo_endpoint"):
                endpoint_names.append("userinfo_endpoint")
            if any(not str(data.get(name, "")).startswith("https://") for name in endpoint_names):
                raise AuthenticationError("OIDC discovery returned a non-HTTPS endpoint")
        self._discovery = (now + 300.0, data)
        return data

    async def _get_jwks(self, uri: str, *, force: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if not force and self._jwks and self._jwks[0] > now:
            return self._jwks[1]
        response = await self.http.get(uri, headers={"Accept": "application/json"})
        response.raise_for_status()
        data = response.json()
        if not isinstance(data.get("keys"), list):
            raise AuthenticationError("OIDC JWKS response is invalid")
        self._jwks = (now + 300.0, data)
        return data

    async def _verify_id_token(
        self, token: str, *, expected_nonce: str, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            header_b64, payload_b64, signature_b64 = token.split(".")
            header = json.loads(_b64url_decode(header_b64))
            claims = json.loads(_b64url_decode(payload_b64))
        except Exception as exc:
            raise AuthenticationError("OIDC ID token is malformed") from exc
        alg = header.get("alg")
        if alg not in {"RS256", "RS384", "RS512"}:
            raise AuthenticationError("OIDC ID token uses an unsupported signing algorithm")
        advertised_algs = metadata.get("id_token_signing_alg_values_supported")
        if isinstance(advertised_algs, list) and advertised_algs and alg not in advertised_algs:
            raise AuthenticationError("OIDC ID token signing algorithm was not advertised by the provider")
        crit = header.get("crit")
        if crit not in (None, []):
            raise AuthenticationError("OIDC ID token contains unsupported critical headers")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise AuthenticationError("OIDC ID token has no key identifier")
        jwks = await self._get_jwks(metadata["jwks_uri"])
        key = next((item for item in jwks["keys"] if item.get("kid") == kid), None)
        if key is None:
            jwks = await self._get_jwks(metadata["jwks_uri"], force=True)
            key = next((item for item in jwks["keys"] if item.get("kid") == kid), None)
        if key is None or key.get("kty") != "RSA":
            raise AuthenticationError("OIDC signing key is unavailable")
        try:
            n = int.from_bytes(_b64url_decode(key["n"]), "big")
            e = int.from_bytes(_b64url_decode(key["e"]), "big")
            public_key = rsa.RSAPublicNumbers(e, n).public_key()
            hash_alg = {"RS256": hashes.SHA256(), "RS384": hashes.SHA384(), "RS512": hashes.SHA512()}[alg]
            public_key.verify(
                _b64url_decode(signature_b64), f"{header_b64}.{payload_b64}".encode("ascii"),
                padding.PKCS1v15(), hash_alg,
            )
        except Exception as exc:
            raise AuthenticationError("OIDC ID token signature validation failed") from exc
        now = int(time.time())
        if claims.get("iss") != self.issuer:
            raise AuthenticationError("OIDC ID token issuer mismatch")
        audience = claims.get("aud")
        audiences = [audience] if isinstance(audience, str) else audience if isinstance(audience, list) else []
        if self.client_id not in audiences:
            raise AuthenticationError("OIDC ID token audience mismatch")
        authorized_party = claims.get("azp")
        if len(audiences) > 1 and authorized_party != self.client_id:
            raise AuthenticationError("OIDC ID token authorized-party mismatch")
        if authorized_party is not None and authorized_party != self.client_id:
            raise AuthenticationError("OIDC ID token authorized-party mismatch")
        if not isinstance(claims.get("exp"), (int, float)) or int(claims["exp"]) <= now:
            raise AuthenticationError("OIDC ID token is expired")
        if isinstance(claims.get("nbf"), (int, float)) and int(claims["nbf"]) > now + 60:
            raise AuthenticationError("OIDC ID token is not valid yet")
        if isinstance(claims.get("iat"), (int, float)) and int(claims["iat"]) > now + 60:
            raise AuthenticationError("OIDC ID token was issued in the future")
        if claims.get("nonce") != expected_nonce:
            raise AuthenticationError("OIDC ID token nonce mismatch")
        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject or len(subject) > 512:
            raise AuthenticationError("OIDC ID token subject is invalid")
        return claims
