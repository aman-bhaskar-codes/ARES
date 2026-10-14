from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from ares.api.settings import Settings


def test_default_schema_revision_tracks_alembic_head(monkeypatch):
    monkeypatch.delenv('REQUIRED_SCHEMA_REVISION', raising=False)
    head = ScriptDirectory.from_config(Config(str(Path('backend/alembic.ini').resolve()))).get_current_head()
    assert Settings(_env_file=None).required_schema_revision == head


def test_schema_override_is_preserved():
    assert Settings(_env_file=None, required_schema_revision='custom').required_schema_revision == 'custom'
