from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
ALEMBIC = ROOT / "backend" / "alembic.ini"
EXPECTED_HEAD = "0012"


def run_upgrade(database_url: str, revision: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    subprocess.run(
        ["alembic", "-c", str(ALEMBIC), "upgrade", revision],
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
