from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def load_dotenv(path: Path = Path('.env')) -> None:
    """Minimal .env loader for local diagnostics; existing process env always wins."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def status(ok: bool, label: str, detail: str) -> bool:
    mark = 'OK' if ok else 'FAIL'
    print(f'[{mark:4}] {label}: {detail}')
    return ok


def command_version(command: str, *args: str) -> str | None:
    if shutil.which(command) is None:
        return None
    try:
        result = subprocess.run(
            [command, *args], check=True, capture_output=True, text=True, timeout=3
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return (result.stdout or result.stderr).strip()


def main() -> int:
    load_dotenv()
    checks: list[bool] = []
    checks.append(status(sys.version_info >= (3, 12), 'Python', platform.python_version()))
    checks.append(status(shutil.which('uv') is not None, 'uv', shutil.which('uv') or 'not found'))

    node_version = command_version('node', '--version')
    checks.append(status(node_version is not None, 'Node', node_version or 'not found'))
    corepack_version = command_version('corepack', '--version')
    checks.append(status(corepack_version is not None, 'Corepack', corepack_version or 'not found'))

    checks.append(status(Path('backend/pyproject.toml').exists(), 'backend', 'backend/pyproject.toml'))
    checks.append(status(Path('apps/web/package.json').exists(), 'frontend', 'apps/web/package.json'))

    mode = os.getenv('ARES_MODE', 'demo')
    database_url = os.getenv('DATABASE_URL', 'sqlite+pysqlite:///./.data/ares-dev.sqlite3')
    checks.append(status(mode in {'demo', 'local_live'}, 'ARES_MODE', mode))
    checks.append(status(bool(database_url), 'DATABASE_URL', database_url.split('@')[-1]))

    max_active_runs = os.getenv('MAX_ACTIVE_RUNS', '4')
    max_job_attempts = os.getenv('MAX_JOB_ATTEMPTS', '3')
    json_logs = os.getenv('JSON_LOGS', 'true').lower()
    checks.append(status(max_active_runs.isdigit() and 1 <= int(max_active_runs) <= 64, 'MAX_ACTIVE_RUNS', max_active_runs))
    checks.append(status(max_job_attempts.isdigit() and 1 <= int(max_job_attempts) <= 20, 'MAX_JOB_ATTEMPTS', max_job_attempts))
    checks.append(status(json_logs in {'true', 'false'}, 'JSON_LOGS', json_logs))

    if mode == 'local_live':
        strict = os.getenv('STRICT_FREE_MODE', 'true').lower() == 'true'
        paid = os.getenv('ALLOW_BILLABLE_PROVIDERS', 'false').lower() == 'true'
        checks.append(status(strict and not paid, 'strict-free policy', f'strict={strict}, paid_fallback={paid}'))
        checks.append(status(bool(os.getenv('SEARXNG_URL')), 'SearXNG', os.getenv('SEARXNG_URL', 'missing')))
        checks.append(status(bool(os.getenv('GEMINI_API_KEY')), 'Gemini key', 'configured' if os.getenv('GEMINI_API_KEY') else 'missing'))
        checks.append(status(os.getenv('GEMINI_THINKING_LEVEL', 'low') in {'low', 'medium', 'high'}, 'Gemini thinking', os.getenv('GEMINI_THINKING_LEVEL', 'low')))
        for name in ('GEMINI_RPM', 'GEMINI_TPM', 'GEMINI_RPD'):
            checks.append(status(bool(os.getenv(name)), name, os.getenv(name, 'missing')))

    print('\nARES doctor reads .env, never prints secrets, and does not make provider calls.')
    return 0 if all(checks) else 1


if __name__ == '__main__':
    raise SystemExit(main())
