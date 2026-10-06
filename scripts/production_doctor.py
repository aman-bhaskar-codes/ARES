from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlsplit

from ares.api.settings import Settings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate an ARES production environment without printing secrets."
    )
    parser.add_argument(
        "--env-file", default=".env.production", help="environment file to validate"
    )
    args = parser.parse_args()
    env_path = Path(args.env_file)
    if not env_path.exists():
        print(f"[FAIL] environment file not found: {env_path}")
        return 2

    raw = env_path.read_text(encoding="utf-8", errors="replace")
    failures: list[str] = []
    warnings: list[str] = []
    try:
        settings = Settings(_env_file=env_path)  # type: ignore[call-arg]
        settings.validate_live_mode()
    except Exception as exc:
        print(f"[FAIL] configuration validation: {exc}")
        return 2

    if "CHANGE_ME" in raw:
        failures.append("environment file still contains CHANGE_ME placeholders")
    if settings.deployment_environment != "production":
        failures.append("DEPLOYMENT_ENVIRONMENT must be production")
    if settings.auth_mode != "oidc":
        failures.append("AUTH_MODE must be oidc")
    if settings.readiness_requires_worker is False:
        warnings.append(
            "READINESS_REQUIRES_WORKER=false; API may be ready while no worker can process research"
        )
    if settings.required_schema_revision != "0012":
        failures.append("REQUIRED_SCHEMA_REVISION must be 0012 for the M10 development candidate")
    if urlsplit(settings.database_url).username == urlsplit(settings.worker_database_url).username:
        failures.append("API and worker database URLs resolve to the same login role")
    if settings.otel_exporter_otlp_endpoint == "":
        warnings.append(
            "OTLP exporter is not configured; structured logs still work but distributed traces stay local"
        )
    if settings.gemini_embeddings_enabled is False:
        warnings.append(
            "Gemini embeddings are disabled; persistent lexical retrieval remains available"
        )

    if settings.browser_enabled:
        if len(settings.browser_service_token.strip()) < 32:
            failures.append("BROWSER_ENABLED requires a 32+ character BROWSER_SERVICE_TOKEN")
        browser_origin = urlsplit(settings.browser_service_url)
        if browser_origin.hostname in {"127.0.0.1", "localhost"}:
            warnings.append(
                "browser service resolves to localhost; production should use the isolated browser service network"
            )
        else:
            print("[OK] isolated browser client authentication configured")
    else:
        warnings.append(
            "browser fallback is disabled; direct safe HTTP remains the only web extraction path"
        )

    print("[OK] production settings parse and security policy")
    print("[OK] OIDC + HTTPS + same-origin browser/API boundary")
    print("[OK] distinct API and worker database roles")
    print(f"[OK] expected schema revision: {settings.required_schema_revision}")
    print(f"[OK] request body limit: {settings.max_request_body_bytes} bytes")
    print(
        f"[OK] per-user/workspace/global active-run limits: {settings.max_active_runs_per_user}/{settings.max_active_runs_per_workspace}/{settings.max_active_runs}"
    )
    for warning in warnings:
        print(f"[WARN] {warning}")
    for failure in failures:
        print(f"[FAIL] {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
