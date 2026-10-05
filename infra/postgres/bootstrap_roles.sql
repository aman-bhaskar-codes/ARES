\set ON_ERROR_STOP on

-- ARES production privilege groups. Concrete LOGIN roles/passwords are created by the
-- deployment secret manager/platform and granted membership in these groups.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ares_api') THEN
    CREATE ROLE ares_api NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ares_worker') THEN
    CREATE ROLE ares_worker NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT BYPASSRLS;
  END IF;
END $$;

-- Apply CONNECT to whichever database this script is run against.
SELECT format('GRANT CONNECT ON DATABASE %I TO ares_api, ares_worker', current_database()) \gexec
GRANT USAGE ON SCHEMA public TO ares_api, ares_worker;

-- Public API: tenant research rows remain constrained by FORCE RLS policies.
GRANT SELECT, INSERT, UPDATE, DELETE ON
  users, workspaces, workspace_memberships, sessions, oidc_states, audit_events,
  conversations, runs, jobs, run_events, sources, document_versions, evidence,
  claims, claim_evidence, user_documents, document_chunks, document_embeddings,
  document_embeddings_pg, artifacts
TO ares_api;
GRANT SELECT, INSERT, DELETE ON asset_versions TO ares_api;
GRANT SELECT, INSERT, UPDATE ON ingestion_jobs TO ares_api;
GRANT SELECT, INSERT ON ingestion_events TO ares_api;
GRANT SELECT ON extraction_versions, evidence_segments, document_tables,
  document_table_cells, asset_renditions, embedding_profiles TO ares_api;
GRANT SELECT ON worker_instances, alembic_version TO ares_api;
GRANT EXECUTE ON FUNCTION ares_global_active_run_count() TO ares_api;

-- Worker: cross-workspace durable-job leasing and evidence persistence are intentional.
-- Never assign this privilege group to the public API or interactive clients.
GRANT SELECT, INSERT, UPDATE, DELETE ON
  runs, jobs, run_events, sources, document_versions, evidence, claims, claim_evidence,
  user_documents, document_chunks, document_embeddings, document_embeddings_pg, artifacts,
  provider_quota_locks, provider_usage, worker_instances, run_steps, resource_leases,
  asset_versions, extraction_versions, evidence_segments, document_tables,
  document_table_cells, asset_renditions, ingestion_jobs, ingestion_events, embedding_profiles
TO ares_worker;
GRANT SELECT ON conversations TO ares_worker;

-- New schema objects receive no automatic runtime grants. Every migration must explicitly
-- review whether the API, worker, both, or neither should receive access (deny by default).

-- Verify after provisioning concrete LOGIN roles:
--   SELECT rolname, rolsuper, rolbypassrls FROM pg_roles
--   WHERE rolname IN ('ares_api','ares_worker');
-- Expected: ares_api => false/false, ares_worker => false/true for superuser/bypassrls.
