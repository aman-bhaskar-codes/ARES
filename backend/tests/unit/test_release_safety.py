from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

from ares.application.code_interpreter import CodeInterpreter


def test_code_execution_cannot_write_host_file(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    result = CodeInterpreter().execute(f"open({str(marker)!r}, 'w').write('unsafe')")
    assert not result.success
    assert not marker.exists()
    assert not CodeInterpreter().is_available()


def test_archive_excludes_private_and_untracked_files(tmp_path: Path, monkeypatch) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
    archive = importlib.import_module("release_archive")
    monkeypatch.setattr(archive, "ROOT", tmp_path)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for name in ["README.md", ".env.local", "private.pem", "untracked.txt", ".env.example"]:
        (tmp_path / name).write_text("synthetic fixture")
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "add",
            "README.md",
            ".env.local",
            "private.pem",
            ".env.example",
        ],
        check=True,
    )
    paths = {p.name for p in archive.source_files()}
    assert paths == {"README.md", ".env.example"}


def test_release_gate_requires_browser_evidence(monkeypatch) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
    verifier = importlib.import_module("verify_v3_release")
    for name in ["ARES_E2E_CONVERSATION_ID", "ARES_E2E_RUN_ID", "ARES_E2E_EVIDENCE_ID"]:
        monkeypatch.delenv(name, raising=False)
    full = verifier.verify(skip_e2e=False, skip_archive=True)
    assert not full["gate_passed"]
    assert full["status"] == "failed"
    partial = verifier.verify(skip_e2e=True, skip_archive=True)
    assert partial["status"] == "preflight_passed"


def test_production_bootstrap_normalizes_url() -> None:
    import json
    import os

    root = Path(__file__).resolve().parents[3]
    line = next(
        line
        for line in (root / "infra/production/compose.yaml").read_text().splitlines()
        if "command:" in line and "bootstrap_url=" in line
    )
    command = json.loads(line.split("command:", 1)[1].strip())[2].replace("$$", "$")
    command = command.split("; psql ", 1)[0] + '; printf "%s" "$bootstrap_url"'
    for url in [
        "postgresql+psycopg://audit:placeholder@localhost/ares",
        "postgresql://audit:placeholder@localhost/ares",
    ]:
        result = subprocess.run(
            ["sh", "-ec", command],
            env={**os.environ, "MIGRATION_DATABASE_URL": url},
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout == "postgresql://audit:placeholder@localhost/ares"
