from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from ares.api.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_default_schema_revision_tracks_alembic_head(monkeypatch):
    monkeypatch.delenv('REQUIRED_SCHEMA_REVISION', raising=False)
    alembic_ini = REPO_ROOT / 'backend' / 'alembic.ini'
    head = ScriptDirectory.from_config(Config(str(alembic_ini))).get_current_head()
    assert Settings(_env_file=None).required_schema_revision == head


def test_schema_override_is_preserved():
    assert Settings(_env_file=None, required_schema_revision='custom').required_schema_revision == 'custom'
