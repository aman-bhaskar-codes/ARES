from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Provision a pinned faster-whisper CTranslate2 model outside request handling."
    )
    parser.add_argument("--model", default="Systran/faster-whisper-small")
    parser.add_argument(
        "--revision",
        required=True,
        help="Exact 40-character Hugging Face commit SHA; branches/tags are intentionally refused.",
    )
    parser.add_argument("--output-dir", default=".data/models/whisper-small-ct2")
    parser.add_argument(
        "--license-reviewed",
        action="store_true",
        help="Confirm the operator reviewed the selected model repository/license before download.",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if not re.fullmatch(r"[0-9a-fA-F]{40}", args.revision):
        raise SystemExit("--revision must be an exact 40-character commit SHA")
    if not args.license_reviewed:
        raise SystemExit("refusing download until --license-reviewed is supplied")

    output = Path(args.output_dir).expanduser().resolve()
    if output.exists() and any(output.iterdir()) and not args.force:
        raise SystemExit(f"output directory is not empty: {output}; use --force only after review")
    output.mkdir(parents=True, exist_ok=True)

    try:
        from faster_whisper.utils import download_model
    except ImportError as exc:
        raise SystemExit(
            "faster-whisper is not installed; install backend/requirements-media.txt first"
        ) from exc

    resolved = Path(
        download_model(
            args.model,
            output_dir=str(output),
            local_files_only=False,
            revision=args.revision,
        )
    ).resolve()
    required = [resolved / "model.bin", resolved / "config.json"]
    missing = [str(path.name) for path in required if not path.is_file()]
    if missing:
        raise SystemExit(f"downloaded model is incomplete; missing: {', '.join(missing)}")

    files = []
    for path in sorted(item for item in resolved.rglob("*") if item.is_file()):
        if path.name == "ARES_MODEL_MANIFEST.json" or ".cache" in path.parts:
            continue
        files.append(
            {
                "path": str(path.relative_to(resolved)),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    manifest = {
        "schema_version": 1,
        "provider": "huggingface",
        "model": args.model,
        "revision": args.revision.lower(),
        "provisioned_at": datetime.now(UTC).isoformat(),
        "files": files,
    }
    manifest_path = resolved / "ARES_MODEL_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(manifest_path)


if __name__ == "__main__":
    main()
