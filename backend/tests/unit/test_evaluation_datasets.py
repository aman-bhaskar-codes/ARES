import json
import os
import subprocess
import sys
from pathlib import Path


def test_frozen_evaluation_cases_and_provenance_are_populated():
    root = Path('evals/datasets')
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
    result = subprocess.run([sys.executable, 'evals/run_suite.py', '--suite', 'all',
        '--repeats', '2', '--report', str(report)], env={**os.environ, 'PYTHONPATH': 'backend/src'},
        capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(report.read_text())
    assert payload['gate_passed']
    assert all(suite['repeat_count'] == 2 and suite['run_variance'] for suite in payload['reports'])
    claims = next(suite for suite in payload['reports'] if suite['suite'] == 'claims')
    assert 'citation_precision' in claims['metrics']
