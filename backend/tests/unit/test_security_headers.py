from ares.api.security_headers import SecurityHeadersMiddleware
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_security_headers_present_on_responses():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, enable_hsts=False)

    @app.get("/api/v1/test")
    def api_test():
        return {"status": "ok"}

    @app.get("/page")
    def page_test():
        return "<html>page</html>"

    client = TestClient(app)

    # API endpoint uses strict default-src 'none'
    api_resp = client.get("/api/v1/test")
    assert api_resp.status_code == 200
    assert api_resp.headers["X-Content-Type-Options"] == "nosniff"
    assert api_resp.headers["X-Frame-Options"] == "DENY"
    assert api_resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "default-src 'none'" in api_resp.headers["Content-Security-Policy"]
    assert "Strict-Transport-Security" not in api_resp.headers

    # SPA/HTML page uses rich default-src 'self'
    page_resp = client.get("/page")
    assert page_resp.status_code == 200
    assert "default-src 'self'" in page_resp.headers["Content-Security-Policy"]


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
