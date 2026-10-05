from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def sidecar_module():
    path = Path(__file__).parents[3] / "services" / "browser" / "app.py"
    spec = importlib.util.spec_from_file_location("ares_browser_sidecar", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_browser_policy_rejects_non_http_and_userinfo(sidecar_module):
    with pytest.raises(ValueError):
        sidecar_module.validate_public_url("file:///etc/passwd")
    with pytest.raises(ValueError):
        sidecar_module.validate_public_url("https://user:secret@example.com/")


def test_browser_policy_rejects_private_dns_result(sidecar_module, monkeypatch):
    monkeypatch.setattr(
        sidecar_module.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("169.254.169.254", 443))],
    )
    with pytest.raises(ValueError):
        sidecar_module.validate_public_url("https://metadata.example/")


def test_browser_policy_accepts_only_all_public_dns_results(sidecar_module, monkeypatch):
    monkeypatch.setattr(
        sidecar_module.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    assert sidecar_module.validate_public_url("https://example.com/article") == "https://example.com/article"


def test_browser_sidecar_requires_bearer_token(sidecar_module, monkeypatch):
    monkeypatch.setenv("ARES_BROWSER_SERVICE_TOKEN", "t" * 40)
    with pytest.raises(sidecar_module.HTTPException) as exc:
        sidecar_module._require_authorization(None)
    assert exc.value.status_code == 401
    sidecar_module._require_authorization("Bearer " + "t" * 40)


@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1", "fe80::1"
])
def test_browser_policy_rejects_private_and_metadata_address_classes(sidecar_module, monkeypatch, address):
    monkeypatch.setattr(
        sidecar_module.socket, "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", (address, 443))],
    )
    with pytest.raises(ValueError, match="non-public"):
        sidecar_module.validate_public_url("https://example.com/path")
