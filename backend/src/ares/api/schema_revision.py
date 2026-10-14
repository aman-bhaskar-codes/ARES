"""Resolve readiness expectations from the migrations shipped with this build."""
from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


@lru_cache(maxsize=1)
def schema_head() -> str:
    backend_root = Path(__file__).resolve().parents[3]
    config = Config(str(backend_root / 'alembic.ini'))
    head = ScriptDirectory.from_config(config).get_current_head()
    if head is None:
        raise RuntimeError('No Alembic schema head is available')
    return head
