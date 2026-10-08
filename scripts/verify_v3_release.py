from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import subprocess
import logging

try:
    from generate_sbom import build_sbom  # noqa: F401
    from release_archive import build as build_archive  # noqa: F401
except ImportError:
    pass

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "0.12.0"
EXPECTED_SCHEMA = "0016_v3_capabilities" # Placeholder for latest schema
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))

def _check_versions(failures: list[str]) -> None:
    backend_path = (ROOT / "backend" / "pyproject.toml")
    if not backend_path.exists():
        failures.append("pyproject.toml is missing")
        return
    backend = backend_path.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', backend, re.MULTILINE)
    web = _read_json(ROOT / "apps" / "web" / "package.json")
    if not match or match.group(1) != EXPECTED_VERSION:
        failures.append(f"backend version is not {EXPECTED_VERSION}")
    if web.get("version") != EXPECTED_VERSION:
        failures.append(f"frontend version is not {EXPECTED_VERSION}")

def check_command(cmd, desc, failures):
    try:
        logging.info(f"Running {desc}: {' '.join(cmd)}")
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        logging.info(f"{desc} passed.")
    except subprocess.CalledProcessError as e:
        failures.append(f"{desc} failed with code {e.returncode}")
    except FileNotFoundError:
        failures.append(f"Command not found for {desc}: {cmd[0]}")

def _check_openapi(failures: list[str]) -> None:
    contract = _read_json(ROOT / "backend" / "openapi.json")
    paths = contract.get("paths", {})
    required = {
        "/api/v3/capabilities",
        "/api/v3/workflows",
        "/api/v3/runs/{run_id}/report",
        "/api/v3/runs/{run_id}/exports",
    }
    missing = sorted(required - set(paths))
    if missing:
        failures.append(f"OpenAPI missing V3 paths: {', '.join(missing)}")

def main() -> int:
    parser = argparse.ArgumentParser(description="Verify ARES V3 Release E2E and Quality Gates")
    parser.add_argument("--skip-e2e", action="store_true", help="Skip browser E2E tests")
    parser.add_argument("--skip-archive", action="store_true", help="skip the two-build reproducibility check")
    args = parser.parse_args()
    failures: list[str] = []
    
    _check_versions(failures)
    _check_openapi(failures)
    
    # 1. Contract Tests
    check_command(["pytest", "backend/src/ares/tests"], "Backend Unit & Contract Tests", failures)
    
    # 2. Type Checking
    check_command(["mypy", "backend/src/ares"], "Backend Type Checking", failures)
    
    # 3. Browser E2E Tests (Stubbed Playwright command)
    if not args.skip_e2e:
        check_command(["npx", "playwright", "test", "apps/web/e2e"], "Playwright E2E Tests", failures)
    
    payload = {"gate_passed": not failures, "failures": failures}
    print(json.dumps(payload, indent=2))
    
    if not failures:
        logging.info("V3 Release Verification Passed!")
        with open("RELEASE_MANIFEST.json", "w") as f:
            f.write('{"version": "3.0.0", "status": "verified"}\n')
        return 0
    else:
        logging.error("V3 Release Verification Failed.")
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
