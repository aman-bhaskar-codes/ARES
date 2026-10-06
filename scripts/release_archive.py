from __future__ import annotations

import argparse
import hashlib
import stat
import zipfile
import json
from pathlib import Path, PurePosixPath

from generate_sbom import render_sbom

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".data",
    "dist",
    "build",
    "coverage",
    ".coverage",
}
EXCLUDED_NAMES = {
    ".env",
    ".env.production",
    ".DS_Store",
    "SBOM.cdx.json",
    "RELEASE_MANIFEST.json",
}


def include(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if any(part in EXCLUDED_PARTS for part in rel.parts):
        return False
    if path.name in EXCLUDED_NAMES or path.suffix in {".pyc", ".pyo", ".tsbuildinfo"}:
        return False
    if len(rel.parts) >= 2 and rel.parts[0:2] == ("evals", "reports") and path.suffix == ".json":
        return False
    return path.is_file()


def _write_bytes(
    archive: zipfile.ZipFile, rel: PurePosixPath, payload: bytes, *, executable: bool = False
) -> None:
    info = zipfile.ZipInfo(str(rel), date_time=(2026, 10, 5, 0, 0, 0))
    perms = 0o755 if executable else 0o644
    info.external_attr = (stat.S_IFREG | perms) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, payload)


def build(output: Path, prefix: str) -> str:
    output = output.resolve()
    checksum = output.with_suffix(output.suffix + ".sha256")
    files = sorted(
        (p for p in ROOT.rglob("*") if include(p) and p.resolve() not in {output, checksum}),
        key=lambda p: p.as_posix(),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    sbom = render_sbom()
    manifest = {
        "product": "ARES",
        "version": "0.12.0",
        "schema_head": "0013_provider_budgets",
        "baseline_archive_sha256": "02321335a16c3fa6ea6713cad5ee6bb964d76d899d54eadc8c400e01ec9079f7",
        "source_file_count": len(files),
        "sbom_sha256": hashlib.sha256(sbom).hexdigest(),
    }
    written_paths = set()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            rel = PurePosixPath(prefix) / PurePosixPath(path.relative_to(ROOT).as_posix())
            if str(rel) in written_paths:
                raise ValueError(f"Duplicate ZIP path detected: {rel}")
            written_paths.add(str(rel))
            mode = path.stat().st_mode
            _write_bytes(archive, rel, path.read_bytes(), executable=bool(mode & stat.S_IXUSR))
        
        sbom_path = PurePosixPath(prefix) / "SBOM.cdx.json"
        if str(sbom_path) in written_paths:
            raise ValueError(f"Duplicate ZIP path detected: {sbom_path}")
        written_paths.add(str(sbom_path))
        _write_bytes(archive, sbom_path, sbom)
        
        manifest_path = PurePosixPath(prefix) / "RELEASE_MANIFEST.json"
        if str(manifest_path) in written_paths:
            raise ValueError(f"Duplicate ZIP path detected: {manifest_path}")
        written_paths.add(str(manifest_path))
        _write_bytes(
            archive,
            manifest_path,
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    return digest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="ARES_M12_release_candidate.zip")
    parser.add_argument("--prefix", default="ARES_M12_release_candidate")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    digest = build(output, args.prefix)
    print(f"{output}\nsha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
