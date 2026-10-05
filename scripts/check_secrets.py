#!/usr/bin/env python3
"""Fail when source-controlled files contain common credential material.

This is a narrow deterministic pre-publication gate, not a substitute for a dedicated secret
scanner. It intentionally avoids entropy heuristics to keep false positives low and CI stable.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("google_api_key", re.compile(r"AIza[0-9A-Za-z_-]{30,}")),
    ("github_token", re.compile(r"gh[pousr]_[0-9A-Za-z]{30,}")),
    ("aws_access_key", re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}")),
)
SKIP_SUFFIXES = {".lock", ".zip", ".bundle", ".png", ".jpg", ".jpeg", ".webp", ".pdf"}
SKIP_NAMES = {"backend/openapi.json"}


def candidate_files() -> list[Path]:
    """Return source candidates in both Git checkouts and clean release archives."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        check=False,
        capture_output=True,
    )
    if result.returncode == 0:
        return [Path(item.decode()) for item in result.stdout.split(b"\0") if item]

    skipped_parts = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".data", "dist", "build"}
    return [
        path
        for path in Path(".").rglob("*")
        if path.is_file() and not any(part in skipped_parts for part in path.parts)
    ]


def main() -> int:
    findings: list[tuple[str, str]] = []
    candidates = candidate_files()
    for path in candidates:
        if str(path) in SKIP_NAMES or path.suffix.lower() in SKIP_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, pattern in PATTERNS:
            if pattern.search(text):
                findings.append((str(path), name))
    if findings:
        for path, name in findings:
            print(f"secret-shaped material detected: {path} ({name})")
        return 2
    print(f"secret scan passed across {len(candidates)} candidate source paths (narrow deterministic patterns)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
