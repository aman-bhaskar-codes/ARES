import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_frozen_evaluation_cases_and_provenance_are_populated():
    root = REPO_ROOT / 'evals' / 'datasets'
    assert len(json.loads((root / 'claim_cases.json').read_text())) >= 100
    retrieval = json.loads((root / 'retrieval_cases.json').read_text())
    assert len(retrieval) >= 50
    assert all(case['relevance_grades'] for case in retrieval)
    manifest = json.loads((root / 'heldout/scifact/manifest.json').read_text())
    assert len(manifest['cases']) == 100
    assert len(manifest['archive_sha256']) == 64
    assert manifest['authoring']['independent_from_implementation'] is True


def test_repeated_offline_regression_emits_variance_and_passes_thresholds(tmp_path):
    report = tmp_path / 'report.json'
    run_suite = str(REPO_ROOT / 'evals' / 'run_suite.py')
    backend_src = str(REPO_ROOT / 'backend' / 'src')
    result = subprocess.run([sys.executable, run_suite, '--suite', 'all',
        '--repeats', '2', '--report', str(report)], env={**os.environ, 'PYTHONPATH': backend_src},
        capture_output=True, text=True, check=False, cwd=str(REPO_ROOT))
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(report.read_text())
    assert payload['gate_passed']
    assert all(suite['repeat_count'] == 2 and suite['run_variance'] for suite in payload['reports'])
    claims = next(suite for suite in payload['reports'] if suite['suite'] == 'claims')
    assert 'citation_precision' in claims['metrics']
