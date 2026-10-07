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
    
    from ares.adapters.db import Base, WorkspaceRow, UserRow, ConversationRow, RunRow, SourceRow
    from sqlalchemy.orm import Session
    
    Base.metadata.create_all(engine)
    
    workspace_id = uuid.uuid4()
    user_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    run_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    with Session(engine) as session:
        session.add(WorkspaceRow(id=workspace_id, name="Recovery Test"))
        session.add(UserRow(id=user_id, subject=f"test-{uuid.uuid4()}"))
        session.flush()
        session.add(ConversationRow(id=conversation_id, workspace_id=workspace_id, created_by_user_id=user_id, title="Test"))
        session.add(RunRow(
            id=run_id,
            conversation_id=conversation_id,
            workspace_id=workspace_id,
            created_by_user_id=user_id,
            query="Restore test",
            mode="research",
            status="completed",
            request_hash="abc",
            idempotency_key="abc",
        ))
        session.flush()
        from datetime import datetime, UTC
        session.add(SourceRow(
            id=doc_id,
            run_id=run_id,
            title="Doc",
            url="http://test.local",
            domain="test.local",
            fetched_at=datetime.now(UTC),
            extraction_method="web",
            content_hash="xyz"
        ))
        session.commit()

    # 2. Run pg_dump
    with tempfile.TemporaryDirectory() as tmpdir:
        dump_path = Path(tmpdir) / "postgres.dump"
        env = os.environ.copy()
        
        # pg_dump
        try:
            subprocess.run(
                ["pg_dump", "--format=custom", "--no-owner", "--no-acl", "--file", str(dump_path), POSTGRES_URL],
                env=env,
                check=True,
                capture_output=True,
                text=True
            )
        except subprocess.CalledProcessError as e:
            print(f"pg_dump failed with stdout: {e.stdout}")
            print(f"pg_dump failed with stderr: {e.stderr}")
            raise
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
            runs = conn.execute(text("SELECT id, query FROM runs WHERE workspace_id = :wid"), {"wid": workspace_id}).fetchall()
            assert len(runs) == 1
            assert runs[0][0] == run_id
            
            docs = conn.execute(text("SELECT id FROM sources WHERE run_id = :rid"), {"rid": run_id}).fetchall()
            assert len(docs) == 1
            assert docs[0][0] == doc_id
            
            # Isolation check
            other_workspace = uuid.uuid4()
            other_runs = conn.execute(text("SELECT id FROM runs WHERE workspace_id = :wid"), {"wid": other_workspace}).fetchall()
            assert len(other_runs) == 0

