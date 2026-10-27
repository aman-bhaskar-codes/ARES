from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from release_archive import build, release_metadata

ROOT = Path(__file__).resolve().parents[1]


def verify(*, skip_e2e: bool, skip_archive: bool) -> dict[str, object]:
    failures: list[str] = []
    metadata = release_metadata()
    web = json.loads((ROOT / "apps/web/package.json").read_text())
    if web.get("version") != metadata["version"]:
        failures.append("Backend and frontend versions differ")
    contract = json.loads((ROOT / "backend/openapi.json").read_text())
    required = {"/api/v1/runs", "/api/v1/conversations", "/api/v1/auth/me", "/api/v1/system/status"}
    if not required.issubset(contract.get("paths", {})):
        failures.append("OpenAPI is missing required paths")
    if not skip_archive:
        with tempfile.TemporaryDirectory(prefix="ares-release-") as tmp:
            first = build(Path(tmp) / "first.zip", "ARES")
            second = build(Path(tmp) / "second.zip", "ARES")
            if first != second:
                failures.append("Release archives are not reproducible")
    if not skip_e2e:
        variables = ["ARES_E2E_CONVERSATION_ID", "ARES_E2E_RUN_ID", "ARES_E2E_EVIDENCE_ID"]
        missing = [name for name in variables if not os.environ.get(name)]
        if missing:
            failures.append("Live browser E2E requires: " + ", ".join(missing))
        else:
            for browser in ["chromium", "firefox", "webkit"]:
                result = subprocess.run(
                    [sys.executable, str(ROOT / "scripts/e2e_m11.py"), "--browser", browser],
                    cwd=ROOT,
                    check=False,
                )
                if result.returncode:
                    failures.append(f"{browser} browser E2E failed")
    partial = skip_e2e or skip_archive
    return {
        **metadata,
        "gate_passed": not failures,
        "status": "failed"
        if failures
        else ("preflight_passed" if partial else "release_checks_passed"),
        "skipped_checks": [
            name
            for name, skipped in [("browser_e2e", skip_e2e), ("archive", skip_archive)]
            if skipped
        ],
        "failures": failures,
        "scope": "Source, archive, and existing browser checks; not live-provider or hosting certification",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Release checks; skipped gates are explicitly preflight only"
    )
    parser.add_argument("--skip-e2e", action="store_true")
    parser.add_argument("--skip-archive", action="store_true")
    args = parser.parse_args()
    payload = verify(skip_e2e=args.skip_e2e, skip_archive=args.skip_archive)
    print(json.dumps(payload, indent=2))
    return 0 if payload["gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
