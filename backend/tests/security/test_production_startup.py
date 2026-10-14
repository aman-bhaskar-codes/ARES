from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from ares.api.app import create_app
from ares.api.settings import Settings


def test_production_cannot_start_without_authentication():
    cfg = Settings(_env_file=None, deployment_environment='production', auth_mode='disabled')
    with pytest.raises(ValueError, match='production requires AUTH_MODE=oidc'):
        create_app(cfg)


def test_production_documentation_is_disabled(tmp_path: Path):
    cfg = Settings(_env_file=None, ares_mode='demo', deployment_environment='production',
        auth_mode='oidc', database_url='postgresql+psycopg://api:secret@localhost/ares',
        worker_database_url='postgresql+psycopg://worker:secret@localhost/ares',
        session_cookie_secure=True, public_base_url='https://ares.example',
        frontend_origin='https://ares.example', oidc_issuer='https://issuer.example',
        oidc_client_id='ares')
    from ares.adapters.db import Base, build_session_factory
    engine, sessions = build_session_factory(f'sqlite+pysqlite:///{tmp_path / "prod.sqlite3"}')
    Base.metadata.create_all(engine)
    with patch('ares.api.app.build_session_factory', return_value=(engine, sessions)):
        app = create_app(cfg)
    client = TestClient(app, base_url='https://ares.example')
    for path in ['/docs', '/redoc', '/openapi.json']:
        assert client.get(path).status_code == 404
