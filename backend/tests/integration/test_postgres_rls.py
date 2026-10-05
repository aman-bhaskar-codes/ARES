from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ares.adapters.db import build_session_factory
from ares.application.auth import AuthStore
from ares.application.identity import principal_scope
from ares.application.repository import Repository

POSTGRES_URL = os.getenv("ARES_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="ARES_TEST_POSTGRES_URL is not configured")


def test_postgres_rls_hides_other_workspace_and_rejects_cross_tenant_insert() -> None:
    assert POSTGRES_URL is not None
    engine, sessions = build_session_factory(POSTGRES_URL)
    store = AuthStore(sessions)
    repo = Repository(sessions)
    suffix = uuid4().hex[:8]
    a = store.upsert_identity(subject=f"rls|a|{suffix}", email=None, display_name="A")
    b = store.upsert_identity(subject=f"rls|b|{suffix}", email=None, display_name="B")
    with principal_scope(a):
        conv_a = repo.create_conversation(f"a-{suffix}")
    with principal_scope(b):
        repo.create_conversation(f"b-{suffix}")

    role = f"ares_rls_test_{suffix}"
    with engine.begin() as connection:
        try:
            connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS'))
        except DBAPIError as exc:
            pytest.skip(f"database user cannot create a temporary RLS role: {exc}")
        connection.execute(text(f'GRANT SELECT, INSERT ON conversations TO "{role}"'))
        connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))

    try:
        with engine.begin() as connection:
            connection.execute(text(f'SET LOCAL ROLE "{role}"'))
            connection.execute(text("SELECT set_config('app.workspace_id', :wid, true)"), {"wid": str(a.workspace_id)})
            visible = connection.execute(text("SELECT id, title FROM conversations ORDER BY title")).all()
            assert [(str(row.id), row.title) for row in visible] == [(str(conv_a.id), f"a-{suffix}")]
            with pytest.raises(DBAPIError):
                connection.execute(
                    text("INSERT INTO conversations (id, workspace_id, created_by_user_id, title, created_at, updated_at) "
                         "VALUES (:id, :workspace, :user_id, 'cross-tenant', now(), now())"),
                    {"id": uuid4(), "workspace": str(b.workspace_id), "user_id": str(b.user_id)},
                )
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
        engine.dispose()


def test_postgres_pool_reuse_clears_tenant_context() -> None:
    """A pooled connection must never carry a previous request tenant into a later transaction."""
    assert POSTGRES_URL is not None
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from ares.adapters.db import TenantSession

    engine = create_engine(POSTGRES_URL, pool_pre_ping=True, pool_size=1, max_overflow=0)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, class_=TenantSession)
    store = AuthStore(sessions)
    repo = Repository(sessions)
    suffix = uuid4().hex[:8]
    principal = store.upsert_identity(subject=f"rls|pool|{suffix}", email=None, display_name="Pool")
    with principal_scope(principal):
        conversation = repo.create_conversation(f"pool-{suffix}")

    role = f"ares_rls_pool_{suffix}"
    with engine.begin() as connection:
        try:
            connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS'))
        except DBAPIError as exc:
            pytest.skip(f"database user cannot create a temporary RLS role: {exc}")
        connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
        connection.execute(text(f'GRANT SELECT ON conversations TO "{role}"'))

    try:
        with principal_scope(principal):
            with sessions.begin() as session:
                session.execute(text(f'SET LOCAL ROLE "{role}"'))
                assert session.scalar(text("SELECT current_setting('app.workspace_id', true)")) == str(principal.workspace_id)
                assert session.scalar(text("SELECT count(*) FROM conversations WHERE id=:id"), {"id": conversation.id}) == 1

        # Same single-connection pool, but deliberately no principal. TenantSession must blank
        # transaction-local settings before RLS evaluates the next query.
        with sessions.begin() as session:
            session.execute(text(f'SET LOCAL ROLE "{role}"'))
            assert session.scalar(text("SELECT current_setting('app.workspace_id', true)")) in {"", None}
            assert session.scalar(text("SELECT count(*) FROM conversations WHERE id=:id"), {"id": conversation.id}) == 0
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
        engine.dispose()


def test_m11_visualization_tables_enforce_workspace_rls_and_api_read_only_grants() -> None:
    """M11 visual artifacts must not create a weaker tenant boundary than run evidence."""
    assert POSTGRES_URL is not None
    from ares.domain.models import RunCreate, RunMode

    engine, sessions = build_session_factory(POSTGRES_URL)
    store = AuthStore(sessions)
    repo = Repository(sessions)
    suffix = uuid4().hex[:8]
    a = store.upsert_identity(subject=f"rls|visual-a|{suffix}", email=None, display_name="Visual A")
    b = store.upsert_identity(subject=f"rls|visual-b|{suffix}", email=None, display_name="Visual B")
    with principal_scope(a):
        conv_a = repo.create_conversation(f"visual-a-{suffix}")
        run_a, _ = repo.create_run(RunCreate(conversation_id=conv_a.id, query="a", mode=RunMode.QUICK), idempotency_key=f"visual-a-{suffix}")
    with principal_scope(b):
        conv_b = repo.create_conversation(f"visual-b-{suffix}")
        run_b, _ = repo.create_run(RunCreate(conversation_id=conv_b.id, query="b", mode=RunMode.QUICK), idempotency_key=f"visual-b-{suffix}")

    dataset_a, dataset_b = uuid4(), uuid4()
    visual_a, visual_b = uuid4(), uuid4()
    with engine.begin() as connection:
        for dataset_id, principal, run_id, digest in (
            (dataset_a, a, run_a.id, "a" * 64),
            (dataset_b, b, run_b.id, "b" * 64),
        ):
            connection.execute(text(
                "INSERT INTO visualization_datasets "
                "(id, workspace_id, run_id, schema_version, dataset_kind, dataset_json, lineage_json, content_hash, created_at) "
                "VALUES (:id, :workspace, :run, 1, 'timeline', '{}'::json, '[]'::json, :hash, now())"
            ), {"id": dataset_id, "workspace": principal.workspace_id, "run": run_id, "hash": digest})
        for visual_id, dataset_id, principal, run_id, digest in (
            (visual_a, dataset_a, a, run_a.id, "c" * 64),
            (visual_b, dataset_b, b, run_b.id, "d" * 64),
        ):
            connection.execute(text(
                "INSERT INTO visualizations "
                "(id, workspace_id, run_id, dataset_id, schema_version, kind, title, description, approved_spec_json, spec_hash, export_metadata_json, created_at) "
                "VALUES (:id, :workspace, :run, :dataset, 1, 'timeline', 'fixture', '', '{}'::json, :hash, '{}'::json, now())"
            ), {"id": visual_id, "workspace": principal.workspace_id, "run": run_id, "dataset": dataset_id, "hash": digest})

    role = f"ares_rls_visual_{suffix}"
    with engine.begin() as connection:
        try:
            connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS'))
        except DBAPIError as exc:
            pytest.skip(f"database user cannot create a temporary M11 RLS role: {exc}")
        connection.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
        connection.execute(text(f'GRANT SELECT, INSERT ON visualization_datasets, visualizations TO "{role}"'))

    try:
        with engine.begin() as connection:
            connection.execute(text(f'SET LOCAL ROLE "{role}"'))
            connection.execute(text("SELECT set_config('app.workspace_id', :wid, true)"), {"wid": str(a.workspace_id)})
            datasets = connection.execute(text("SELECT id FROM visualization_datasets ORDER BY id")).scalars().all()
            visuals = connection.execute(text("SELECT id FROM visualizations ORDER BY id")).scalars().all()
            assert datasets == [dataset_a]
            assert visuals == [visual_a]
            with pytest.raises(DBAPIError):
                connection.execute(text(
                    "INSERT INTO visualization_datasets "
                    "(id, workspace_id, run_id, schema_version, dataset_kind, dataset_json, lineage_json, content_hash, created_at) "
                    "VALUES (:id, :workspace, :run, 1, 'timeline', '{}'::json, '[]'::json, :hash, now())"
                ), {"id": uuid4(), "workspace": b.workspace_id, "run": run_b.id, "hash": "e" * 64})

        with engine.begin() as connection:
            api_role_exists = connection.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='ares_api')"))
            if api_role_exists:
                assert connection.scalar(text("SELECT has_table_privilege('ares_api', 'visualizations', 'SELECT')")) is True
                assert connection.scalar(text("SELECT has_table_privilege('ares_api', 'visualizations', 'INSERT')")) is False
                assert connection.scalar(text("SELECT has_table_privilege('ares_api', 'visualization_datasets', 'SELECT')")) is True
                assert connection.scalar(text("SELECT has_table_privilege('ares_api', 'visualization_datasets', 'INSERT')")) is False
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
        engine.dispose()
