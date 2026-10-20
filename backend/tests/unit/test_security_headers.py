from ares.api.security_headers import SecurityHeadersMiddleware
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_security_headers_present_on_responses():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, enable_hsts=False)

    @app.get("/test")
    def hello():
        return {"status": "ok"}

    client = TestClient(app)
    response = client.get("/test")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert "Strict-Transport-Security" not in response.headers


def test_security_headers_with_hsts_when_enabled():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, enable_hsts=True)

    @app.get("/test")
    def hello():
        return {"status": "ok"}

    client = TestClient(app)
    response = client.get("/test")
    assert response.status_code == 200
    assert "Strict-Transport-Security" in response.headers
    assert "max-age=31536000" in response.headers["Strict-Transport-Security"]
