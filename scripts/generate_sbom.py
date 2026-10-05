from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]


def _python_components() -> list[dict[str, object]]:
    lock = tomllib.loads((ROOT / "backend" / "uv.lock").read_text(encoding="utf-8"))
    components: list[dict[str, object]] = []
    for package in lock.get("package", []):
        name = str(package.get("name", "")).strip()
        version = str(package.get("version", "")).strip()
        if not name or not version:
            continue
        components.append({
            "type": "library",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{name}@{version}",
            "properties": [{"name": "ares:ecosystem", "value": "python"}],
        })
    return components


_PNPM_PACKAGE = re.compile(r"^  (?P<quoted>'[^']+'|[^:\n]+):\s*$")


def _split_pnpm_key(raw: str) -> tuple[str, str] | None:
    value = raw[1:-1] if raw.startswith("'") and raw.endswith("'") else raw
    if value.startswith("@"):
        slash = value.find("/")
        at = value.find("@", slash + 1)
    else:
        at = value.rfind("@")
    if at <= 0 or at == len(value) - 1:
        return None
    name, version = value[:at], value[at + 1 :]
    if "(" in version:  # snapshot peer-resolution key, not a package definition
        return None
    return name, version


def _node_components() -> list[dict[str, object]]:
    text = (ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8")
    in_packages = False
    components: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for line in text.splitlines():
        if line == "---":
            in_packages = False
            continue
        if line == "packages:":
            in_packages = True
            continue
        if line == "snapshots:":
            in_packages = False
            continue
        if not in_packages:
            continue
        match = _PNPM_PACKAGE.match(line)
        if not match:
            continue
        parsed = _split_pnpm_key(match.group("quoted"))
        if parsed is None or parsed in seen:
            continue
        seen.add(parsed)
        name, version = parsed
        if name.startswith("@") and "/" in name:
            namespace, package_name = name.split("/", 1)
            purl_name = f"{namespace.replace('@', '%40', 1)}/{package_name}"
        else:
            purl_name = name
        components.append({
            "type": "library",
            "name": name,
            "version": version,
            "purl": f"pkg:npm/{purl_name}@{version}",
            "properties": [{"name": "ares:ecosystem", "value": "node"}],
        })
    return components


def build_sbom() -> dict[str, object]:
    components = _python_components() + _node_components()
    components.sort(key=lambda item: (str(item["purl"])))
    fingerprint = hashlib.sha256(
        "\n".join(str(component["purl"]) for component in components).encode("utf-8")
    ).hexdigest()
    serial = uuid5(NAMESPACE_URL, f"ares-sbom:{fingerprint}")
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "ARES",
                "version": "0.11.0",
                "properties": [
                    {"name": "ares:schema-head", "value": "0012_visual_artifacts"},
                    {"name": "ares:source-fingerprint", "value": fingerprint},
                ],
            }
        },
        "components": components,
    }


def render_sbom() -> bytes:
    return (json.dumps(build_sbom(), indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a deterministic CycloneDX SBOM from committed lockfiles")
    parser.add_argument("--output", default="dist/ARES_M11.sbom.cdx.json")
    args = parser.parse_args()
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = render_sbom()
    output.write_bytes(payload)
    print(f"{output}\nsha256={hashlib.sha256(payload).hexdigest()}\ncomponents={len(build_sbom()['components'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
