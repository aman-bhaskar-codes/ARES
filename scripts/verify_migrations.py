from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
ALEMBIC = ROOT / "backend" / "alembic.ini"
MIGRATIONS_DIR = ROOT / "backend" / "migrations" / "versions"


def _discover_head() -> str:
    """Auto-detect the highest migration revision by scanning filenames.

    Migration files follow the pattern ``0NNN_description.py`` where ``0NNN``
    is the revision id. This removes the need to hardcode EXPECTED_HEAD every
    time a new migration is added.
    """
    pattern = re.compile(r"^(\d{4})_.*\.py$")
    revisions: list[str] = []
    for p in MIGRATIONS_DIR.iterdir():
        m = pattern.match(p.name)
        if m:
            revisions.append(m.group(1))
    if not revisions:
        raise SystemExit("no migration files found")
    return sorted(revisions)[-1]


EXPECTED_HEAD = _discover_head()


def run_upgrade(database_url: str, revision: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC), "upgrade", revision],
        cwd=ROOT,
        env=env,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def revision(database_url: str) -> str:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return str(connection.scalar(text("SELECT version_num FROM alembic_version LIMIT 1")))
    finally:
        engine.dispose()


def assert_upgrade(tmp: str, start: str | None) -> None:
    label = "empty" if start is None else f"from-{start}"
    database_url = f"sqlite+pysqlite:///{Path(tmp) / f'{label}.sqlite3'}"
    if start is not None:
        run_upgrade(database_url, start)
        if revision(database_url) != start:
            raise SystemExit(f"precondition upgrade did not reach {start}")
    run_upgrade(database_url, "head")
    if revision(database_url) != EXPECTED_HEAD:
        raise SystemExit(f"{label} upgrade did not reach {EXPECTED_HEAD}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ares-migrations-") as tmp:
        assert_upgrade(tmp, None)
        # M11 must upgrade the direct M10 predecessor plus representative earlier V2/V1 data.
        assert_upgrade(tmp, "0011")
        assert_upgrade(tmp, "0010")
        assert_upgrade(tmp, "0009")
        assert_upgrade(tmp, "0007")
        assert_upgrade(tmp, "0006")
    print(f"migration verification passed: empty/0011/0010/0009/0007/0006 -> {EXPECTED_HEAD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
