from __future__ import annotations

import os
import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text


POSTGRES_URL = os.getenv("ARES_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="ARES_TEST_POSTGRES_URL is not configured")

def test_m12_backup_and_restore_rehearsal() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    
    # 1. Setup initial state
    tenant_id = uuid.uuid4()
    run_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    


    # Create workspace, document, and media blob via repository
    # Wait, doing this via SQL is easier to avoid missing repository methods
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO tenants (id, created_at) VALUES (:tid, now()) ON CONFLICT DO NOTHING"), {"tid": tenant_id})
        conn.execute(text("INSERT INTO runs (id, tenant_id, name, created_at, updated_at) VALUES (:rid, :tid, 'Restore Test', now(), now())"), {"rid": run_id, "tid": tenant_id})
        conn.execute(text("INSERT INTO sources (id, tenant_id, status) VALUES (:sid, :tid, 'indexed')"), {"sid": doc_id, "tid": tenant_id})

    # 2. Run pg_dump
    with tempfile.TemporaryDirectory() as tmpdir:
        dump_path = Path(tmpdir) / "postgres.dump"
        env = os.environ.copy()
        
        # pg_dump
        subprocess.run(
            ["pg_dump", "--format=custom", "--no-owner", "--no-acl", "--file", str(dump_path), POSTGRES_URL],
            env=env,
            check=True
        )
        assert dump_path.exists()
        
        # 3. Simulate failure (wipe data)
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE sources CASCADE"))
            conn.execute(text("TRUNCATE TABLE runs CASCADE"))
        
        # 4. Restore
        subprocess.run(
            ["pg_restore", "--clean", "--if-exists", "--no-owner", "--no-acl", "--dbname", POSTGRES_URL, str(dump_path)],
            env=env,
            check=True
        )
        
        # 5. Validate references and isolation
        with engine.connect() as conn:
            runs = conn.execute(text("SELECT id, name FROM runs WHERE tenant_id = :tid"), {"tid": tenant_id}).fetchall()
            assert len(runs) == 1
            assert runs[0][0] == run_id
            
            docs = conn.execute(text("SELECT id FROM sources WHERE tenant_id = :tid"), {"tid": tenant_id}).fetchall()
            assert len(docs) == 1
            assert docs[0][0] == doc_id
            
            # Isolation check
            other_tenant = uuid.uuid4()
            other_runs = conn.execute(text("SELECT id FROM runs WHERE tenant_id = :tid"), {"tid": other_tenant}).fetchall()
            assert len(other_runs) == 0

