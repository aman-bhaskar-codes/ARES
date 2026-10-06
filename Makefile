.PHONY: doctor connectivity-doctor connectivity-doctor-strict infra migrate verify-migrations production-doctor test test-postgres test-media test-compile openapi eval-routing eval-regression eval-multimodal eval-m10-retrieval eval-m11-heldout lint security-scan lock-check sbom verify-m11-release release-m11 test-e2e check api worker install-media worker-media provision-whisper web load-smoke perf-baseline perf-m10

doctor:
	PYTHONPATH=backend/src uv run --project backend uv run --project backend python scripts/doctor.py

connectivity-doctor:
	@test -f .env || (echo ".env is required" && exit 1)
	PYTHONPATH=backend/src uv run --project backend uv run --project backend python scripts/connectivity_doctor.py --env-file .env --network

connectivity-doctor-strict:
	@test -f .env || (echo ".env is required" && exit 1)
	PYTHONPATH=backend/src uv run --project backend uv run --project backend python scripts/connectivity_doctor.py --env-file .env --network --require-optional

infra:
	docker compose -f infra/local/compose.yaml up -d postgres searxng

migrate:
	uv run --project backend alembic -c backend/alembic.ini upgrade head

verify-migrations:
	PYTHONPATH=backend/src uv run --project backend uv run --project backend python scripts/verify_migrations.py

production-doctor:
	@test -f .env.production || (echo ".env.production is required" && exit 1)
	PYTHONPATH=backend/src uv run --project backend uv run --project backend python scripts/production_doctor.py --env-file .env.production

lock-check:
	uv lock --project backend --check

test:
	PYTHONPATH=backend/src uv run --project backend pytest backend/tests -q

test-postgres:
	@test -n "$$ARES_TEST_POSTGRES_URL" || (echo "ARES_TEST_POSTGRES_URL is required" && exit 1)
	PYTHONPATH=backend/src uv run --project backend pytest \
		backend/tests/integration/test_postgres_concurrency.py \
		backend/tests/integration/test_postgres_pgvector.py \
		backend/tests/integration/test_postgres_rls.py \
		backend/tests/integration/test_postgres_release_readiness.py -q

test-media:
	PYTHONPATH=backend/src uv run --project backend pytest \
		backend/tests/integration/test_m09_media.py \
		backend/tests/unit/test_media_capabilities.py \
		backend/tests/unit/test_gemini_multimodal.py \
		backend/tests/unit/test_body_limit.py -q

eval-multimodal:
	@test -n "$$ARES_MEDIA_EVAL_MANIFEST" || (echo "ARES_MEDIA_EVAL_MANIFEST is required" && exit 1)
	@test -n "$$WHISPER_MODEL_PATH" || (echo "WHISPER_MODEL_PATH is required" && exit 1)
	@test -n "$$WHISPER_MODEL_REVISION" || (echo "WHISPER_MODEL_REVISION is required" && exit 1)
	PYTHONPATH=backend/src uv run --project backend uv run --project backend python scripts/eval_media.py \
		--manifest "$$ARES_MEDIA_EVAL_MANIFEST" --model-path "$$WHISPER_MODEL_PATH" \
		--model-revision "$$WHISPER_MODEL_REVISION" --report evals/reports/media_latest.json

provision-whisper:
	@test -n "$$WHISPER_MODEL_REVISION" || (echo "WHISPER_MODEL_REVISION must be an exact commit SHA" && exit 1)
	PYTHONPATH=backend/src uv run --project backend uv run --project backend python scripts/provision_whisper_model.py \
		--revision "$$WHISPER_MODEL_REVISION" --license-reviewed

test-compile:
	PYTHONPATH=backend/src uv run --project backend python -m compileall -q backend/src backend/tests scripts

openapi:
	PYTHONPATH=backend/src uv run --project backend uv run --project backend python scripts/export_openapi.py

eval-routing:
	PYTHONPATH=backend/src uv run --project backend python evals/run_suite.py --suite routing --decision-provider deterministic

eval-regression:
	PYTHONPATH=backend/src uv run --project backend python evals/run_suite.py --suite all --decision-provider deterministic --retrieval-mode lexical --report evals/reports/regression_latest.json


eval-m11-heldout:
	@test -n "$$ARES_M11_HELDOUT_MANIFEST" || (echo "ARES_M11_HELDOUT_MANIFEST is required" && exit 1)
	uv run --project backend python scripts/validate_m11_heldout.py "$$ARES_M11_HELDOUT_MANIFEST" --minimum-cases 100

lint:
	uv run --project backend ruff check backend/src backend/tests evals scripts

security-scan:
	uv run --project backend python scripts/check_secrets.py

perf-baseline:
	PYTHONPATH=backend/src uv run --project backend uv run --project backend python scripts/perf_baseline.py --runs 60

load-smoke:
	PYTHONPATH=backend/src uv run --project backend uv run --project backend python scripts/load_smoke.py

sbom:
	uv run --project backend python scripts/generate_sbom.py --output dist/ARES_M11.sbom.cdx.json

verify-m11-release:
	PYTHONPATH=backend/src uv run --project backend python scripts/verify_m11_release.py


release-m11: verify-m11-release sbom
	uv run --project backend python scripts/release_archive.py --output dist/ARES_M11_release_candidate.zip --prefix ARES_M11_release_candidate

test-e2e:
	@test -n "$$ARES_E2E_CONVERSATION_ID" || (echo "ARES_E2E_CONVERSATION_ID is required" && exit 1)
	@test -n "$$ARES_E2E_RUN_ID" || (echo "ARES_E2E_RUN_ID is required" && exit 1)
	@test -n "$$ARES_E2E_EVIDENCE_ID" || (echo "ARES_E2E_EVIDENCE_ID is required" && exit 1)
	uv run --project backend python scripts/e2e_m11.py --browser chromium
	uv run --project backend python scripts/e2e_m11.py --browser firefox
	uv run --project backend python scripts/e2e_m11.py --browser webkit

check: doctor lock-check lint security-scan test eval-regression test-compile verify-migrations openapi verify-m11-release

api:
	PYTHONPATH=backend/src uv run --project backend uvicorn ares.api.app:app --reload

worker:
	PYTHONPATH=backend/src uv run --project backend python -m ares.worker.main

install-media:
	uv pip install --python backend/.venv/bin/python --requirement backend/requirements-media.txt

worker-media:
	WORKER_PROFILE=media PYTHONPATH=backend/src uv run --project backend python -m ares.worker.main

web:
	pnpm --filter @ares/web dev

perf-m10:
	PYTHONPATH=backend/src uv run --project backend uv run --project backend python scripts/perf_m10_discovery.py --runs 30

eval-m10-retrieval:
	PYTHONPATH=backend/src uv run --project backend uv run --project backend python scripts/eval_m10_retrieval.py
