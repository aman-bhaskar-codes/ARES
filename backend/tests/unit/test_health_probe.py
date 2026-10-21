from ares.api.health_probe import build_probe_request


def test_container_probe_uses_public_host_without_changing_loopback_target(monkeypatch):
    monkeypatch.setenv('PUBLIC_BASE_URL', 'https://ares.example')
    request = build_probe_request('/health/ready')
    assert request.full_url == 'http://127.0.0.1:8000/health/ready'
    assert request.get_header('Host') == 'ares.example'
