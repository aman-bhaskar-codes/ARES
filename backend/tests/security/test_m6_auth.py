from __future__ import annotations

import base64
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient

from ares.adapters.db import Base, build_session_factory
from ares.api.app import create_app
from ares.api.settings import Settings
from ares.application.auth import AuthStore, AuthenticationError, OidcClient, safe_return_path
from ares.application.identity import Principal, WorkspaceRole, principal_scope
from ares.application.repository import NotFoundError, Repository


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _jwk(public_key, kid: str = "k1") -> dict[str, str]:
    numbers = public_key.public_numbers()
    return {
        "kty": "RSA",
        "kid": kid,
        "alg": "RS256",
        "use": "sig",
        "n": _b64(numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")),
        "e": _b64(numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")),
    }


def _jwt(private_key, claims: dict[str, object], kid: str = "k1") -> str:
    header = _b64(
        json.dumps({"alg": "RS256", "kid": kid, "typ": "JWT"}, separators=(",", ":")).encode()
    )
    payload = _b64(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}".encode()
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{payload}.{_b64(signature)}"


def test_safe_return_path_never_allows_external_origin() -> None:
    assert safe_return_path("https://attacker.example/x") == "/"
    assert safe_return_path("//attacker.example/x") == "/"
    assert safe_return_path("/\\attacker.example/x") == "/"
    assert safe_return_path("/research\nInjected: yes") == "/"
    assert safe_return_path("/research?q=one") == "/research?q=one"


@pytest.mark.asyncio
async def test_oidc_pkce_signature_nonce_and_one_time_state(tmp_path: Path) -> None:
    engine, sessions = build_session_factory(f"sqlite+pysqlite:///{tmp_path / 'oidc.sqlite3'}")
    Base.metadata.create_all(engine)
    store = AuthStore(sessions)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    issuer = "https://issuer.example"
    now = int(time.time())
    seen_verifier: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": issuer,
                    "authorization_endpoint": issuer + "/authorize",
                    "token_endpoint": issuer + "/token",
                    "jwks_uri": issuer + "/jwks",
                    "userinfo_endpoint": issuer + "/userinfo",
                },
            )
        if request.url.path.endswith("/jwks"):
            return httpx.Response(200, json={"keys": [_jwk(private_key.public_key())]})
        if request.url.path.endswith("/token"):
            body = parse_qs(request.content.decode())
            verifier = body["code_verifier"][0]
            seen_verifier.append(verifier)
            pending_nonce = test_oidc_pkce_signature_nonce_and_one_time_state.nonce
            token = _jwt(
                private_key,
                {
                    "iss": issuer,
                    "sub": "user-123",
                    "aud": "ares-client",
                    "exp": now + 300,
                    "iat": now,
                    "nonce": pending_nonce,
                    "email": "u@example.com",
                },
            )
            return httpx.Response(
                200, json={"id_token": token, "access_token": "ephemeral-provider-token"}
            )
        if request.url.path.endswith("/userinfo"):
            assert request.headers["Authorization"] == "Bearer ephemeral-provider-token"
            return httpx.Response(200, json={"sub": "user-123", "name": "Researcher"})
        raise AssertionError(request.url)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OidcClient(
        issuer=issuer,
        client_id="ares-client",
        client_secret="",
        redirect_uri="http://localhost/callback",
        scopes="openid email profile",
        state_ttl_seconds=600,
        session_ttl_hours=12,
        store=store,
        http=http,
    )
    login_url = await client.begin_login("/research")
    params = parse_qs(urlparse(login_url).query)
    assert params["code_challenge_method"] == ["S256"]
    assert params["state"] and params["nonce"]
    test_oidc_pkce_signature_nonce_and_one_time_state.nonce = params["nonce"][0]
    result = await client.complete_login(code="code-1", state=params["state"][0])
    assert result.return_path == "/research"
    assert result.principal.email == "u@example.com"
    assert seen_verifier and len(seen_verifier[0]) > 40
    assert store.resolve_session(result.session_token) is not None
    with pytest.raises(AuthenticationError, match="already consumed"):
        await client.complete_login(code="code-2", state=params["state"][0])
    await http.aclose()


@pytest.mark.asyncio
async def test_oidc_rejects_tampered_signature_and_nonce(tmp_path: Path) -> None:
    engine, sessions = build_session_factory(f"sqlite+pysqlite:///{tmp_path / 'oidc-bad.sqlite3'}")
    Base.metadata.create_all(engine)
    store = AuthStore(sessions)
    good_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    bad_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    issuer = "https://issuer.example"
    metadata = {"issuer": issuer, "jwks_uri": issuer + "/jwks"}

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"keys": [_jwk(good_key.public_key())]})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OidcClient(
        issuer=issuer,
        client_id="client",
        client_secret="",
        redirect_uri="http://localhost/cb",
        scopes="openid",
        state_ttl_seconds=600,
        session_ttl_hours=12,
        store=store,
        http=http,
    )
    now = int(time.time())
    tampered = _jwt(
        bad_key,
        {"iss": issuer, "sub": "s", "aud": "client", "exp": now + 60, "iat": now, "nonce": "n"},
    )
    with pytest.raises(AuthenticationError, match="signature"):
        await client._verify_id_token(tampered, expected_nonce="n", metadata=metadata)
    wrong_nonce = _jwt(
        good_key,
        {"iss": issuer, "sub": "s", "aud": "client", "exp": now + 60, "iat": now, "nonce": "wrong"},
    )
    with pytest.raises(AuthenticationError, match="nonce"):
        await client._verify_id_token(wrong_nonce, expected_nonce="n", metadata=metadata)
    await http.aclose()


def test_workspace_isolation_in_repository(tmp_path: Path) -> None:
    engine, sessions = build_session_factory(f"sqlite+pysqlite:///{tmp_path / 'tenants.sqlite3'}")
    Base.metadata.create_all(engine)
    store = AuthStore(sessions)
    repo = Repository(sessions)
    a = store.upsert_identity(subject="issuer|a", email="a@example.com", display_name="A")
    b = store.upsert_identity(subject="issuer|b", email="b@example.com", display_name="B")
    with principal_scope(a):
        conv_a = repo.create_conversation("A private")
        assert [x.title for x in repo.list_conversations()] == ["A private"]
    with principal_scope(b):
        assert repo.list_conversations() == []
        with pytest.raises(NotFoundError):
            repo.list_runs_for_conversation(conv_a.id)


def test_csrf_and_viewer_role_are_enforced(tmp_path: Path) -> None:
    db = f"sqlite+pysqlite:///{tmp_path / 'api-auth.sqlite3'}"
    engine, sessions = build_session_factory(db)
    Base.metadata.create_all(engine)
    store = AuthStore(sessions)
    principal = store.upsert_identity(
        subject="issuer|viewer", email="v@example.com", display_name="Viewer"
    )
    # downgrade membership before issuing the browser session
    from ares.adapters.db import WorkspaceMembershipRow
    from sqlalchemy import select

    with sessions.begin() as session:
        membership = session.scalar(
            select(WorkspaceMembershipRow).where(
                WorkspaceMembershipRow.workspace_id == principal.workspace_id,
                WorkspaceMembershipRow.user_id == principal.user_id,
            )
        )
        membership.role = WorkspaceRole.VIEWER.value
    principal = Principal(
        user_id=principal.user_id,
        workspace_id=principal.workspace_id,
        role=WorkspaceRole.VIEWER,
        subject=principal.subject,
        email=principal.email,
        display_name=principal.display_name,
    )
    token, csrf = "session-secret", "csrf-secret"
    principal = store.create_session(principal, token=token, csrf_token=csrf, ttl_hours=12)

    settings = Settings(
        ares_mode="demo",
        auth_mode="oidc",
        oidc_issuer="https://issuer.example",
        oidc_client_id="client",
        frontend_origin="http://testserver",
        public_base_url="http://testserver",
        database_url=db,
    )
    client = TestClient(create_app(settings))
    client.cookies.set(settings.session_cookie_name, token)
    client.cookies.set(settings.csrf_cookie_name, csrf)
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["role"] == "viewer"
    no_csrf = client.post("/api/v1/conversations", json={"title": "blocked"})
    assert no_csrf.status_code == 403 and no_csrf.json()["detail"]["code"] == "CSRF_ORIGIN"
    blocked = client.post(
        "/api/v1/conversations",
        json={"title": "blocked"},
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
    )
    assert blocked.status_code == 403 and blocked.json()["detail"]["code"] == "ROLE_FORBIDDEN"


@pytest.mark.asyncio
async def test_oidc_rejects_invalid_authorized_party_and_not_before(tmp_path: Path) -> None:
    engine, sessions = build_session_factory(
        f"sqlite+pysqlite:///{tmp_path / 'oidc-claims.sqlite3'}"
    )
    Base.metadata.create_all(engine)
    store = AuthStore(sessions)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    issuer = "https://issuer.example"
    metadata = {
        "issuer": issuer,
        "jwks_uri": issuer + "/jwks",
        "id_token_signing_alg_values_supported": ["RS256"],
    }

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"keys": [_jwk(key.public_key())]})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OidcClient(
        issuer=issuer,
        client_id="client",
        client_secret="",
        redirect_uri="http://localhost/cb",
        scopes="openid",
        state_ttl_seconds=600,
        session_ttl_hours=12,
        store=store,
        http=http,
    )
    now = int(time.time())
    bad_azp = _jwt(
        key,
        {
            "iss": issuer,
            "sub": "s",
            "aud": ["client", "other"],
            "azp": "other",
            "exp": now + 60,
            "iat": now,
            "nonce": "n",
        },
    )
    with pytest.raises(AuthenticationError, match="authorized-party"):
        await client._verify_id_token(bad_azp, expected_nonce="n", metadata=metadata)
    future = _jwt(
        key,
        {
            "iss": issuer,
            "sub": "s",
            "aud": "client",
            "exp": now + 300,
            "nbf": now + 120,
            "iat": now,
            "nonce": "n",
        },
    )
    with pytest.raises(AuthenticationError, match="not valid yet"):
        await client._verify_id_token(future, expected_nonce="n", metadata=metadata)
    await http.aclose()


@pytest.mark.asyncio
async def test_oidc_discovery_rejects_non_https_endpoints_for_https_issuer(tmp_path: Path) -> None:
    engine, sessions = build_session_factory(
        f"sqlite+pysqlite:///{tmp_path / 'oidc-discovery.sqlite3'}"
    )
    Base.metadata.create_all(engine)
    store = AuthStore(sessions)
    issuer = "https://issuer.example"

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "issuer": issuer,
                "authorization_endpoint": issuer + "/authorize",
                "token_endpoint": "http://issuer.example/token",
                "jwks_uri": issuer + "/jwks",
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OidcClient(
        issuer=issuer,
        client_id="client",
        client_secret="",
        redirect_uri="https://ares.example/cb",
        scopes="openid",
        state_ttl_seconds=600,
        session_ttl_hours=12,
        store=store,
        http=http,
    )
    with pytest.raises(AuthenticationError, match="non-HTTPS"):
        await client._get_discovery()
    await http.aclose()


def test_workspace_switch_rebinds_session_and_logout_revokes_it(tmp_path: Path) -> None:
    from sqlalchemy import select
    from ares.adapters.db import WorkspaceMembershipRow

    db = f"sqlite+pysqlite:///{tmp_path / 'switch-logout.sqlite3'}"
    engine, sessions = build_session_factory(db)
    Base.metadata.create_all(engine)
    store = AuthStore(sessions)
    primary = store.upsert_identity(
        subject="issuer|primary", email="p@example.com", display_name="Primary"
    )
    secondary = store.upsert_identity(
        subject="issuer|secondary", email="s@example.com", display_name="Secondary"
    )
    with sessions.begin() as session:
        existing = session.scalar(
            select(WorkspaceMembershipRow).where(
                WorkspaceMembershipRow.workspace_id == secondary.workspace_id,
                WorkspaceMembershipRow.user_id == primary.user_id,
            )
        )
        if existing is None:
            session.add(
                WorkspaceMembershipRow(
                    workspace_id=secondary.workspace_id,
                    user_id=primary.user_id,
                    role=WorkspaceRole.EDITOR.value,
                    created_at=datetime.now(UTC),
                )
            )

    token, csrf = "switch-session-secret", "switch-csrf-secret"
    store.create_session(primary, token=token, csrf_token=csrf, ttl_hours=12)
    settings = Settings(
        ares_mode="demo",
        auth_mode="oidc",
        oidc_issuer="https://issuer.example",
        oidc_client_id="client",
        frontend_origin="http://testserver",
        public_base_url="http://testserver",
        database_url=db,
    )
    client = TestClient(create_app(settings))
    client.cookies.set(settings.session_cookie_name, token)
    client.cookies.set(settings.csrf_cookie_name, csrf)
    headers = {"Origin": "http://testserver", "X-CSRF-Token": csrf}

    switched = client.post(
        "/api/v1/auth/workspace",
        json={"workspace_id": str(secondary.workspace_id)},
        headers=headers,
    )
    assert switched.status_code == 200
    assert switched.json()["workspace_id"] == str(secondary.workspace_id)
    assert switched.json()["role"] == "editor"
    assert client.get("/api/v1/auth/me").json()["workspace_id"] == str(secondary.workspace_id)

    logged_out = client.post("/api/v1/auth/logout", headers=headers)
    assert logged_out.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
