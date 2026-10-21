from ares.api.rate_limit import RateLimitMiddleware, SlidingWindowRateLimiter
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_sliding_window_rate_limiter_logic():
    limiter = SlidingWindowRateLimiter(rpm=3, window_seconds=60.0)
    client_id = "test_client"

    allowed, _ = limiter.is_allowed(client_id, now=100.0)
    assert allowed
    allowed, _ = limiter.is_allowed(client_id, now=101.0)
    assert allowed
    allowed, _ = limiter.is_allowed(client_id, now=102.0)
    assert allowed

    # 4th request exceeds limit of 3
    allowed, retry_after = limiter.is_allowed(client_id, now=103.0)
    assert not allowed
    assert retry_after > 0.0

    # After window passes, allowed again
    allowed, _ = limiter.is_allowed(client_id, now=161.0)
    assert allowed


def test_rate_limit_middleware_blocks_abusive_requests():
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        enabled=True,
        runs_rpm=2,
        upload_rpm=2,
        write_rpm=2,
    )

    @app.post("/api/v1/runs")
    def create_run():
        return {"run_id": "ok"}

    @app.get("/api/v1/runs")
    def list_runs():
        return []

    client = TestClient(app)

    # First 2 POST requests pass
    r1 = client.post("/api/v1/runs")
    assert r1.status_code == 200
    r2 = client.post("/api/v1/runs")
    assert r2.status_code == 200

    # 3rd POST request is throttled
    r3 = client.post("/api/v1/runs")
    assert r3.status_code == 429
    assert "Retry-After" in r3.headers
    assert r3.json()["detail"]["code"] == "RATE_LIMIT_EXCEEDED"

    # GET requests are not throttled by write rate limits
    r_get = client.get("/api/v1/runs")
    assert r_get.status_code == 200


def test_rate_limit_middleware_disabled_mode():
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        enabled=False,
        runs_rpm=1,
    )

    @app.post("/api/v1/runs")
    def create_run():
        return {"run_id": "ok"}

    client = TestClient(app)
    for _ in range(5):
        res = client.post("/api/v1/runs")
        assert res.status_code == 200
