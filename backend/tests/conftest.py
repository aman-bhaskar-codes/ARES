from __future__ import annotations

from pathlib import Path

import pytest

from ares.adapters.db import Base, build_session_factory
from ares.application.repository import Repository


@pytest.fixture
def repository(tmp_path: Path) -> Repository:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'test.sqlite3'}"
    engine, sessions = build_session_factory(database_url)
    Base.metadata.create_all(engine)
    return Repository(sessions)
