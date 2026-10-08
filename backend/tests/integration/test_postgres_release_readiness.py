from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from ares.api.app import create_app
from ares.api.settings import Settings

POSTGRES_URL = os.getenv("ARES_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="ARES_TEST_POSTGRES_URL is not configured")


def test_production_readiness_requires_expected_schema_and_trusted_host() -> None:
    assert POSTGRES_URL is not None
    settings = Settings(
        ares_mode="demo",
        deployment_environment="production",
        auth_mode="oidc",
        oidc_issuer="https://issuer.example",
        oidc_client_id="client",
        public_base_url="https://testserver",
        frontend_origin="https://testserver",
        session_cookie_secure=True,
        database_url=POSTGRES_URL,
        worker_database_url=POSTGRES_URL + "?application_name=ares-worker-test",
        required_schema_revision="0013",
        readiness_requires_worker=False,
    )
    from ares.adapters.db import build_session_factory
    from sqlalchemy import text
    engine, _ = build_session_factory(POSTGRES_URL)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"))
        connection.execute(text("DELETE FROM alembic_version"))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('0013')"))
    engine.dispose()
    
    client = TestClient(create_app(settings), base_url="https://testserver")
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    rejected_host = client.get("/health/live", headers={"Host": "attacker.example"})
    assert rejected_host.status_code == 400
