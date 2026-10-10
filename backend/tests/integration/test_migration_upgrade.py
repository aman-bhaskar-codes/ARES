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
        assert {'outline', 'assessment', 'model_provider', 'plugins', 'related_questions'} <= {c['name'] for c in inspector.get_columns('runs')}
        assert inspector.has_table('retrieval_traces')
        profile_fk = next(fk for fk in inspector.get_foreign_keys('document_embeddings')
                          if fk['constrained_columns'] == ['profile_id'])
        assert profile_fk['referred_table'] == 'retrieval_profiles'
        with engine.connect() as connection:
            assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0021'
    finally:
        engine.dispose()


def test_upgrade_accepts_schema_already_created_by_development_bootstrap(tmp_path):
    from ares.adapters.db import Base
    root = Path(__file__).resolve().parents[3]
    url = f'sqlite+pysqlite:///{tmp_path / "bootstrapped.sqlite3"}'
    env = {**os.environ, 'DATABASE_URL': url}
    subprocess.run([sys.executable, '-m', 'alembic', '-c', str(root / 'backend/alembic.ini'), 'upgrade', '0016'], cwd=root, env=env, check=True, capture_output=True)
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        for name, kind in [('outline', 'JSON'), ('assessment', 'JSON'), ('model_provider', 'VARCHAR(24)'), ('plugins', 'JSON'), ('related_questions', 'JSON')]:
            connection.execute(text(f'ALTER TABLE runs ADD COLUMN {name} {kind}'))
    result = subprocess.run([sys.executable, '-m', 'alembic', '-c', str(root / 'backend/alembic.ini'), 'upgrade', 'head'], cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0021'
    engine.dispose()
