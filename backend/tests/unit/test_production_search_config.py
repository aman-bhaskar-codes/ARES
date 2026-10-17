import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_production_mounts_no_development_search_secret():
    path = REPO_ROOT / 'scripts' / 'check_secrets.py'
    spec = importlib.util.spec_from_file_location('secret_scan', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.production_config_findings(REPO_ROOT / 'infra' / 'production' / 'compose.yaml') == []


def test_secret_scan_detects_development_production_mount(tmp_path):
    config = tmp_path / 'settings.yml'
    config.write_text('secret_key: development-only')
    compose = tmp_path / 'compose.yaml'
    compose.write_text('services:\n  search:\n    volumes:\n      - ./settings.yml:/etc/searxng/settings.yml:ro\n')
    path = REPO_ROOT / 'scripts' / 'check_secrets.py'
    spec = importlib.util.spec_from_file_location('secret_scan', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.production_config_findings(compose)
