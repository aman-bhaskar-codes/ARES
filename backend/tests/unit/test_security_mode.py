from __future__ import annotations

import pytest
from ares.api.settings import Settings


def test_disabled_auth_permits_loopback_hosts() -> None:
    # 127.0.0.1 (default)
    settings = Settings(auth_mode="disabled")
    settings.validate_security_mode()

    # localhost
    settings_lh = Settings(
        auth_mode="disabled",
        public_base_url="http://localhost:8000",
        server_bind_host="localhost",
    )
    settings_lh.validate_security_mode()

    # IPv6 loopback
    settings_ipv6 = Settings(
        auth_mode="disabled",
        public_base_url="http://[::1]:8000",
        server_bind_host="::1",
    )
    settings_ipv6.validate_security_mode()

    # testserver (FastAPI TestClient)
    settings_ts = Settings(
        auth_mode="disabled",
        public_base_url="http://testserver",
        server_bind_host="testserver",
    )
    settings_ts.validate_security_mode()


@pytest.mark.parametrize(
    "insecure_public_url",
    [
        "http://0.0.0.0:8000",
        "http://192.168.1.100:8000",
        "https://ares.internal.org",
        "http://ares.example.com:8000",
    ],
)
def test_disabled_auth_rejects_non_loopback_public_base_url(insecure_public_url: str) -> None:
    settings = Settings(
        auth_mode="disabled",
        public_base_url=insecure_public_url,
    )
    with pytest.raises(ValueError, match="AUTH_MODE=disabled is restricted to local loopback hosts"):
        settings.validate_security_mode()


@pytest.mark.parametrize(
    "insecure_bind_host",
    [
        "0.0.0.0",  # noqa: S104
        "192.168.1.50",
        "ares.example.com",
    ],
)
def test_disabled_auth_rejects_non_loopback_server_bind_host(insecure_bind_host: str) -> None:
    settings = Settings(
        auth_mode="disabled",
        server_bind_host=insecure_bind_host,
    )
    with pytest.raises(ValueError, match="AUTH_MODE=disabled is restricted to local loopback hosts"):
        settings.validate_security_mode()


def test_disabled_auth_allows_non_loopback_with_explicit_override() -> None:
    settings = Settings(
        auth_mode="disabled",
        public_base_url="http://192.168.1.50:8000",
        server_bind_host="0.0.0.0",  # noqa: S104
        allow_insecure_remote_disabled_auth=True,
    )
    settings.validate_security_mode()

