from pathlib import Path
import importlib.util


def test_production_mounts_no_development_search_secret():
    path = Path('scripts/check_secrets.py')
    spec = importlib.util.spec_from_file_location('secret_scan', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.production_config_findings(Path('infra/production/compose.yaml')) == []


def test_secret_scan_detects_development_production_mount(tmp_path):
    config = tmp_path / 'settings.yml'
    config.write_text('secret_key: development-only')
    compose = tmp_path / 'compose.yaml'
    compose.write_text('services:\n  search:\n    volumes:\n      - ./settings.yml:/etc/searxng/settings.yml:ro\n')
    path = Path('scripts/check_secrets.py')
    spec = importlib.util.spec_from_file_location('secret_scan', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.production_config_findings(compose)
