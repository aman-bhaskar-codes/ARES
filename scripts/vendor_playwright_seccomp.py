from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from urllib.request import Request, urlopen

PLAYWRIGHT_VERSION = "v1.63.0"
SOURCE_URL = (
    "https://raw.githubusercontent.com/microsoft/playwright/"
    f"{PLAYWRIGHT_VERSION}/utils/docker/seccomp_profile.json"
)
# GitHub blob SHA returned for the exact v1.63.0 upstream file. Checking Git's blob object
# identity protects this vendoring step from a mutable/mismatched response without requiring
# ARES to maintain an independently copied security profile.
EXPECTED_GIT_BLOB_SHA1 = "fddc05fb520affb145404e6f6f647ca96af8087d"
DEFAULT_DESTINATION = Path("infra/browser/seccomp_profile.json")


def git_blob_sha1(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload, usedforsecurity=False).hexdigest()


def validate(payload: bytes) -> None:
    digest = git_blob_sha1(payload)
    if digest != EXPECTED_GIT_BLOB_SHA1:
        raise RuntimeError(
            f"Playwright seccomp profile identity mismatch: expected {EXPECTED_GIT_BLOB_SHA1}, got {digest}"
        )
    if b'"defaultAction"' not in payload or b'"clone"' not in payload or b'"unshare"' not in payload:
        raise RuntimeError("Playwright seccomp profile is structurally incomplete")


def main() -> int:
    parser = argparse.ArgumentParser(description="Vendor the exact Playwright v1.63.0 Chromium seccomp profile")
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--check", action="store_true", help="validate an already-vendored file without network access")
    args = parser.parse_args()

    if args.check:
        payload = args.destination.read_bytes()
        validate(payload)
        print(f"[OK] {args.destination} matches Playwright {PLAYWRIGHT_VERSION} blob {EXPECTED_GIT_BLOB_SHA1}")
        return 0

    request = Request(SOURCE_URL, headers={"User-Agent": "ARES-M10-release-vendor/1"})
    with urlopen(request, timeout=20) as response:  # noqa: S310 - pinned HTTPS host + immutable tag + blob check
        payload = response.read(256_000)
    validate(payload)
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_bytes(payload)
    print(f"[OK] wrote {args.destination} ({len(payload)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
