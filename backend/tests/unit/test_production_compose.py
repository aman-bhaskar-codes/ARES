import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_production_compose_parses_and_keeps_search_dependencies(tmp_path):
    docker = shutil.which('docker')
    if docker is None:
        pytest.skip('Docker CLI is unavailable; config validation does not require its daemon')
    env_file = tmp_path / 'production.env'
    env_file.write_text('PUBLIC_BASE_URL=https://ares.example\n')
    env = {**os.environ, 'ARES_IMAGE': 'ares:test', 'ARES_MEDIA_IMAGE': 'ares-media:test',
        'ARES_ENV_FILE': str(env_file), 'MIGRATION_DATABASE_URL': 'postgresql://admin:test@postgres/ares',
        'POSTGRES_ADMIN_USER': 'admin', 'POSTGRES_ADMIN_PASSWORD': 'test',
        'SEARXNG_SECRET': 'test-only-search-secret-32-characters'}
    compose_file = str(REPO_ROOT / 'infra' / 'production' / 'compose.yaml')
    result = subprocess.run([docker, 'compose', '-f', compose_file,
        'config', '--format', 'json'], env=env, capture_output=True, text=True, check=False,
        cwd=str(REPO_ROOT))
    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)['services']
    for name in ['api', 'worker']:
        assert services[name]['depends_on']['searxng']['condition'] == 'service_healthy'
    assert services['api']['healthcheck']['test'][-1] == '/health/ready'
