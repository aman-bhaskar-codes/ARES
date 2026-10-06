import pytest

from ares.api.settings import Settings


def test_demo_needs_no_key() -> None:
    Settings(ares_mode="demo").validate_live_mode()


def test_live_mode_requires_explicit_quota_and_key() -> None:
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        Settings(ares_mode="local_live", gemini_api_key="").validate_live_mode()

    with pytest.raises(ValueError, match="GEMINI_RPM"):
        Settings(ares_mode="local_live", gemini_api_key="x", gemini_rpm=None).validate_live_mode()


def test_live_mode_rejects_billable_flag() -> None:
    with pytest.raises(ValueError, match="refuses"):
        Settings(
            ares_mode="local_live",
            gemini_api_key="x",
            gemini_rpm=1,
            gemini_tpm=1,
            gemini_rpd=1,
            allow_billable_providers=True,
        ).validate_live_mode()


def test_live_mode_requires_strict_free_mode() -> None:
    with pytest.raises(ValueError, match="STRICT_FREE_MODE"):
        Settings(
            ares_mode="local_live",
            strict_free_mode=False,
            gemini_api_key="x",
            gemini_rpm=10,
            gemini_tpm=10_000,
            gemini_rpd=100,
        ).validate_live_mode()


def test_production_security_requires_one_https_origin_and_distinct_worker_role() -> None:
    base = dict(
        deployment_environment="production",
        auth_mode="oidc",
        oidc_issuer="https://id.example",
        oidc_client_id="client",
        public_base_url="https://ares.example",
        frontend_origin="https://ares.example",
        session_cookie_secure=True,
        database_url="postgresql+psycopg://api@db/ares",
        worker_database_url="postgresql+psycopg://worker@db/ares",
    )
    Settings(**base).validate_security_mode()
    with pytest.raises(ValueError, match="share one origin"):
        Settings(**{**base, "frontend_origin": "https://ui.example"}).validate_security_mode()
    with pytest.raises(ValueError, match="distinct WORKER_DATABASE_URL"):
        Settings(**{**base, "worker_database_url": base["database_url"]}).validate_security_mode()
    with pytest.raises(ValueError, match="OIDC_ISSUER must use HTTPS"):
        Settings(**{**base, "oidc_issuer": "http://id.example"}).validate_security_mode()


def test_request_body_limit_must_cover_upload_limit() -> None:
    with pytest.raises(ValueError, match="MAX_REQUEST_BODY_BYTES"):
        Settings(max_upload_bytes=10_000, max_request_body_bytes=5_000).validate_security_mode()


def test_example_environment_allows_blank_optional_quota_values() -> None:
    from pathlib import Path

    settings = Settings(_env_file=Path(".env.example"))  # type: ignore[call-arg]
    assert settings.ares_mode == "demo"
    assert settings.gemini_rpm is None
    assert settings.gemini_tpm is None
    assert settings.gemini_rpd is None
    assert settings.gemini_embedding_rpm is None
    settings.validate_live_mode()


def test_browser_feature_requires_strong_internal_service_token():
    with pytest.raises(ValueError, match="BROWSER_SERVICE_TOKEN"):
        Settings(browser_enabled=True, browser_service_token="short").validate_security_mode()
    Settings(
        browser_enabled=True,
        browser_service_url="http://browser:8090",
        browser_service_token="b" * 40,
    ).validate_security_mode()


def test_browser_service_url_must_be_origin_only():
    with pytest.raises(ValueError, match="origin"):
        Settings(
            browser_enabled=True,
            browser_service_url="http://browser:8090/v1/render",
            browser_service_token="b" * 40,
        ).validate_security_mode()
