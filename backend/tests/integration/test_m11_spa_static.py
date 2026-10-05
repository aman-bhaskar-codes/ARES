from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ares.api.spa_static import SpaStaticFiles


def _client(tmp_path: Path) -> TestClient:
    (tmp_path / "index.html").write_text("<main>ARES shell</main>", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('ares')", encoding="utf-8")
    app = FastAPI()
    app.mount("/", SpaStaticFiles(directory=tmp_path, html=True), name="web")
    return TestClient(app)


def test_browser_router_deep_link_receives_application_shell(tmp_path: Path) -> None:
    response = _client(tmp_path).get(
        "/research/conversation-1/runs/run-1/evidence/evidence-1?view=sources",
        headers={"Accept": "text/html"},
    )
    assert response.status_code == 200
    assert "ARES shell" in response.text


def test_missing_assets_and_unknown_api_paths_remain_404(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.get("/missing.js", headers={"Accept": "text/html"}).status_code == 404
    assert client.get("/api/v9/does-not-exist", headers={"Accept": "text/html"}).status_code == 404
    assert client.get("/research/conversation-1", headers={"Accept": "application/json"}).status_code == 404

from ares.api.app import create_app
from ares.api.settings import Settings


def test_oidc_static_shell_is_public_but_api_remains_authenticated(tmp_path: Path) -> None:
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<main>ARES authenticated shell</main>", encoding="utf-8")
    db = f"sqlite+pysqlite:///{tmp_path / 'oidc-static.sqlite3'}"
    settings = Settings(
        ares_mode="demo",
        auth_mode="oidc",
        oidc_issuer="https://issuer.example",
        oidc_client_id="client",
        frontend_origin="http://testserver",
        public_base_url="http://testserver",
        database_url=db,
        web_dist_dir=str(web),
    )
    client = TestClient(create_app(settings))

    root = client.get("/", headers={"Accept": "text/html"})
    assert root.status_code == 200
    assert "ARES authenticated shell" in root.text
    assert "script-src 'self'" in root.headers["content-security-policy"]
    assert "style-src 'self' 'unsafe-inline'" in root.headers["content-security-policy"]

    deep_link = client.get(
        "/research/conversation-1/runs/run-1?view=answer",
        headers={"Accept": "text/html"},
    )
    assert deep_link.status_code == 200
    assert "ARES authenticated shell" in deep_link.text

    protected = client.get("/api/v1/auth/me")
    assert protected.status_code == 401
    assert protected.json()["detail"]["code"] == "AUTH_REQUIRED"
