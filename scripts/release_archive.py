from __future__ import annotations

import argparse
import ast
import hashlib
import json
import stat
import subprocess
import tomllib
import zipfile
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
    "backups",
    ".kilo",
    ".vscode",
    ".coverage",
}
EXCLUDED_NAMES = {
    ".env",
    ".env.production",
    ".DS_Store",
    "id_rsa",
    "id_ed25519",
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
    if path.name.startswith(".env") and not path.name.endswith(".example"):
        return False
    if path.suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".dump", ".sqlite3", ".db"}:
        return False
    return not path.is_symlink() and path.is_file()


def source_files() -> list[Path]:
    """Only Git-tracked regular source files may enter a release archive."""
    result = subprocess.run(  # noqa: S603 — fixed Git inventory command
        ["git", "-C", str(ROOT), "ls-files", "-z"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    return sorted(
        [
            ROOT / name.decode("utf-8")
            for name in result.stdout.split(b"\0")
            if name and include(ROOT / name.decode("utf-8"))
        ],
        key=lambda path: path.as_posix(),
    )


def release_metadata() -> dict[str, str]:
    project = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text())
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in (ROOT / "backend" / "migrations" / "versions").glob("*.py"):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Assign):
                names = [target.id for target in node.targets if isinstance(target, ast.Name)]
                if "revision" in names:
                    revisions.add(ast.literal_eval(node.value))
                if "down_revision" in names:
                    parent = ast.literal_eval(node.value)
                    if parent:
                        parents.update([parent] if isinstance(parent, str) else parent)
    heads = revisions - parents
    if len(heads) != 1:
        raise ValueError(f"Expected one migration head, found {sorted(heads)}")
    return {"version": project["project"]["version"], "schema_head": heads.pop()}


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
        (p for p in source_files() if p.resolve() not in {output, checksum}),
        key=lambda p: p.as_posix(),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    sbom = render_sbom()
    manifest = {
        "product": "ARES",
        **release_metadata(),
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
