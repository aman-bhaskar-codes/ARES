import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


def test_clean_sqlite_database_upgrades_to_complete_schema(tmp_path):
    root = Path(__file__).resolve().parents[3]
    url = f"sqlite+pysqlite:///{tmp_path / 'migration.sqlite3'}"
    result = subprocess.run(
        [sys.executable, '-m', 'alembic', '-c', str(root / 'backend/alembic.ini'), 'upgrade', 'head'],
        cwd=root, env={**os.environ, 'DATABASE_URL': url}, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        assert {'outline', 'assessment'} <= {c['name'] for c in inspector.get_columns('runs')}
        assert inspector.has_table('retrieval_traces')
        profile_fk = next(fk for fk in inspector.get_foreign_keys('document_embeddings')
                          if fk['constrained_columns'] == ['profile_id'])
        assert profile_fk['referred_table'] == 'retrieval_profiles'
        with engine.connect() as connection:
            assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0019'
    finally:
        engine.dispose()
