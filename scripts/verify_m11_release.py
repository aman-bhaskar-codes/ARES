from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path

from generate_sbom import build_sbom
from release_archive import build as build_archive

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "0.11.0"
EXPECTED_SCHEMA = "0012_visual_artifacts"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _check_versions(failures: list[str]) -> None:
    backend = (ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', backend, re.MULTILINE)
    web = _read_json(ROOT / "apps" / "web" / "package.json")
    if not match or match.group(1) != EXPECTED_VERSION:
        failures.append("backend version is not 0.11.0")
    if web.get("version") != EXPECTED_VERSION:
        failures.append("frontend version is not 0.11.0")


def _check_schema(failures: list[str]) -> None:
    migration = ROOT / "backend" / "migrations" / "versions" / "0012_visual_artifacts.py"
    if not migration.is_file():
        failures.append("0012_visual_artifacts migration is missing")
    for path in (ROOT / ".env.example", ROOT / ".env.production.example"):
        text = path.read_text(encoding="utf-8")
        if "REQUIRED_SCHEMA_REVISION=0012" not in text:
            failures.append(f"{path.name} does not require schema revision 0012")


def _check_frontend_lock(failures: list[str]) -> None:
    lock_path = ROOT / "pnpm-lock.yaml"
    if not lock_path.is_file() or lock_path.stat().st_size == 0:
        failures.append("pnpm-lock.yaml is missing")
        return
    root_manifest = _read_json(ROOT / "package.json")
    manifest = _read_json(ROOT / "apps" / "web" / "package.json")
    lock = lock_path.read_text(encoding="utf-8")
    package_manager = str(root_manifest.get("packageManager", ""))
    if package_manager != "pnpm@12.8.1":
        failures.append("root packageManager must remain pinned to pnpm@12.8.1")
    # pnpm 12 treats the pinned package manager as a config dependency. Without this
    # document `pnpm install --frozen-lockfile` fails before checking application deps.
    manager_marker = "packageManagerDependencies:\n      pnpm:\n        specifier: 12.8.1\n        version: 12.8.1"
    if manager_marker not in lock:
        failures.append("pnpm lock is missing pnpm@12.8.1 packageManagerDependencies")
    if lock.count("lockfileVersion: '9.0'") < 2:
        failures.append("pnpm 12 multi-document lock contract is incomplete")
    for name, version in {**manifest.get("dependencies", {}), **manifest.get("devDependencies", {})}.items():
        marker = f"      {name}:\n        specifier: {version}\n"
        quoted = f"      '{name}':\n        specifier: {version}\n"
        if marker not in lock and quoted not in lock:
            failures.append(f"pnpm lock importer missing {name}@{version}")


def _check_openapi(failures: list[str]) -> None:
    contract = _read_json(ROOT / "backend" / "openapi.json")
    paths = contract.get("paths", {})
    required = {
        "/api/v2/runs/{run_id}/visualizations",
        "/api/v2/runs/{run_id}/visualizations/{visualization_id}/export.csv",
    }
    missing = sorted(required - set(paths))
    if missing:
        failures.append(f"OpenAPI missing M11 paths: {', '.join(missing)}")
        return
    export = paths["/api/v2/runs/{run_id}/visualizations/{visualization_id}/export.csv"]
    content = export.get("get", {}).get("responses", {}).get("200", {}).get("content", {})
    if "text/csv" not in content:
        failures.append("OpenAPI visualization export does not advertise text/csv")


def _check_actions_pinned(failures: list[str]) -> None:
    for path in (ROOT / ".github" / "workflows").glob("*.yml"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped.startswith("uses:") and " uses:" not in line:
                continue
            value = stripped.split("uses:", 1)[1].strip().split()[0]
            if value.startswith("./") or "@" not in value:
                continue
            ref = value.rsplit("@", 1)[1]
            if not FULL_SHA.fullmatch(ref):
                failures.append(f"unpinned GitHub Action at {path.relative_to(ROOT)}:{number}: {value}")


def _check_docs(failures: list[str]) -> None:
    required = [
        "docs/adr/011-validated-visualization-artifacts.md",
        "docs/architecture/V2_RELEASE_ARCHITECTURE.md",
        "docs/development/V2_MODEL_LICENSE_INVENTORY.md",
        "docs/evaluation/M11_RELEASE_EVALUATION_PROTOCOL.md",
        "docs/evaluation/EXTERNAL_TESTER_PROTOCOL.md",
        "docs/demo/M11_DEMO_RECORDING.md",
        "evals/datasets/heldout/manifest.example.json",
        "docs/operations/V2_RESOURCE_PROFILES.md",
        "docs/operations/TROUBLESHOOTING.md",
    ]
    for rel in required:
        if not (ROOT / rel).is_file():
            failures.append(f"release documentation missing: {rel}")


def _check_sbom(failures: list[str]) -> None:
    sbom = build_sbom()
    components = sbom.get("components", [])
    purls = {item.get("purl") for item in components if isinstance(item, dict)}
    required = {
        "pkg:npm/echarts@6.1.0",
        "pkg:npm/%40xyflow/react@12.12.0",
        "pkg:npm/react-markdown@10.1.0",
        "pkg:npm/remark-gfm@4.0.1",
    }
    missing = sorted(required - purls)
    if missing:
        failures.append(f"SBOM is missing locked M11 frontend packages: {', '.join(missing)}")


def _check_archive_reproducibility(failures: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="ares-m11-release-") as directory:
        first = Path(directory) / "first.zip"
        second = Path(directory) / "second.zip"
        build_archive(first, "ARES_M11_release_candidate")
        build_archive(second, "ARES_M11_release_candidate")
        one = hashlib.sha256(first.read_bytes()).hexdigest()
        two = hashlib.sha256(second.read_bytes()).hexdigest()
        if one != two:
            failures.append("release archive is not reproducible across two consecutive builds")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify source-level M11/V2 release invariants")
    parser.add_argument("--skip-archive", action="store_true", help="skip the two-build reproducibility check")
    args = parser.parse_args()
    failures: list[str] = []
    _check_versions(failures)
    _check_schema(failures)
    _check_frontend_lock(failures)
    _check_openapi(failures)
    _check_actions_pinned(failures)
    _check_docs(failures)
    _check_sbom(failures)
    if not args.skip_archive:
        _check_archive_reproducibility(failures)
    payload = {"gate_passed": not failures, "failures": failures}
    print(json.dumps(payload, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
