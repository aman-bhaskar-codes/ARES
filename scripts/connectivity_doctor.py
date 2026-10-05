from __future__ import annotations

import argparse
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import httpx
from sqlalchemy import text

from ares.adapters.arxiv import ArxivAcademicProvider
from ares.adapters.crossref import CrossrefAcademicProvider
from ares.adapters.db import build_session_factory
from ares.adapters.openalex import OpenAlexAcademicProvider
from ares.adapters.searxng import SearXNGSearchProvider
from ares.api.settings import Settings
from ares.application.observability import telemetry_export_status
from ares.domain.research import SearchRequest


@dataclass(frozen=True)
class CheckResult:
    name: str
    required: bool
    ok: bool
    detail: str


def _print(result: CheckResult) -> None:
    if result.ok:
        state = "OK"
    elif result.required:
        state = "FAIL"
    else:
        state = "WARN"
    print(f"[{state:4}] {result.name}: {result.detail}")


def _db_check(settings: Settings) -> CheckResult:
    engine = None
    try:
        engine, _ = build_session_factory(settings.database_url)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            try:
                revision = connection.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar_one()
            except Exception:
                return CheckResult("database/schema", True, False, "connected, but alembic_version is unavailable")
        expected = settings.required_schema_revision
        return CheckResult(
            "database/schema",
            True,
            str(revision) == expected,
            f"connected; revision={revision}; expected={expected}",
        )
    except Exception as exc:
        return CheckResult("database/schema", True, False, f"{type(exc).__name__}: {exc}")
    finally:
        if engine is not None:
            engine.dispose()


def _searxng_check(settings: Settings, timeout: float) -> CheckResult:
    provider = SearXNGSearchProvider(settings.searxng_url, timeout_seconds=timeout)
    try:
        provider.search(SearchRequest(query="ARES connectivity check", limit=1, timeout_seconds=timeout))
        return CheckResult("SearXNG", settings.ares_mode == "local_live", True, "search API responded with valid JSON")
    except Exception as exc:
        return CheckResult("SearXNG", settings.ares_mode == "local_live", False, f"{type(exc).__name__}: {exc}")
    finally:
        provider.close()


def _gemini_check(settings: Settings, timeout: float) -> CheckResult:
    required = settings.ares_mode == "local_live"
    if not settings.gemini_api_key:
        return CheckResult("Gemini", required, not required, "API key not configured")
    try:
        from google import genai  # type: ignore[import-not-found]
        from google.genai import types  # type: ignore[import-not-found]

        client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(timeout=max(1, int(timeout * 1000))),
        )
        try:
            model = client.models.get(model=settings.gemini_model)
            resolved = getattr(model, "name", None) or settings.gemini_model
            return CheckResult("Gemini", required, True, f"credentials/model metadata accepted ({resolved})")
        finally:
            client.close()
    except Exception as exc:
        return CheckResult("Gemini", required, False, f"{type(exc).__name__}: {exc}")


def _oidc_check(settings: Settings, timeout: float) -> CheckResult:
    required = settings.auth_mode == "oidc"
    if not required:
        return CheckResult("OIDC discovery", False, True, "disabled")
    endpoint = urljoin(settings.oidc_issuer.rstrip("/") + "/", ".well-known/openid-configuration")
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            response = client.get(endpoint, headers={"Accept": "application/json"})
            response.raise_for_status()
            payload = response.json()
        issuer = payload.get("issuer")
        authorization_endpoint = payload.get("authorization_endpoint")
        token_endpoint = payload.get("token_endpoint")
        jwks_uri = payload.get("jwks_uri")
        ok = all(isinstance(value, str) and value.startswith("https://") for value in [issuer, authorization_endpoint, token_endpoint, jwks_uri])
        if not ok:
            return CheckResult("OIDC discovery", required, False, "discovery document is missing required HTTPS endpoints")
        if issuer.rstrip("/") != settings.oidc_issuer.rstrip("/"):
            return CheckResult("OIDC discovery", required, False, "discovery issuer does not match OIDC_ISSUER")
        return CheckResult("OIDC discovery", required, True, "issuer, authorization, token and JWKS endpoints validated")
    except Exception as exc:
        return CheckResult("OIDC discovery", required, False, f"{type(exc).__name__}: {exc}")


def _academic_check(name: str, provider, timeout: float) -> CheckResult:
    try:
        provider.search_documents("evidence based research", limit=1, timeout_seconds=timeout)
        return CheckResult(name, False, True, "read-only API responded")
    except Exception as exc:
        return CheckResult(name, False, False, f"{type(exc).__name__}: {exc}")
    finally:
        provider.close()


def _github_check(settings: Settings, timeout: float) -> CheckResult:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ARES-research/0.7 connectivity-doctor",
    }
    if settings.github_read_token.strip():
        headers["Authorization"] = f"Bearer {settings.github_read_token.strip()}"
    try:
        with httpx.Client(base_url="https://api.github.com", timeout=timeout, headers=headers) as client:
            response = client.get("/rate_limit")
            response.raise_for_status()
            payload = response.json()
        remaining = ((payload.get("resources") or {}).get("core") or {}).get("remaining")
        return CheckResult("GitHub REST", False, True, f"authenticated/public API accepted request; remaining={remaining}")
    except Exception as exc:
        return CheckResult("GitHub REST", False, False, f"{type(exc).__name__}: {exc}")


def _jev_check(settings: Settings, timeout: float) -> CheckResult:
    if not settings.jev_enabled:
        return CheckResult("Jev", False, True, "disabled by policy")
    if not settings.jev_api_key:
        return CheckResult("Jev", False, False, "enabled but API key is missing")
    # Jev is intentionally not called by the connectivity doctor because its endpoint is metered.
    # Configuration validation is enough here; semantic calls stay inside explicitly budgeted runs.
    return CheckResult("Jev", False, True, f"configured endpoint={settings.jev_base_url}; no metered call performed")


def _static_checks(settings: Settings) -> list[CheckResult]:
    results: list[CheckResult] = []
    results.append(CheckResult("settings", True, True, f"mode={settings.ares_mode}; auth={settings.auth_mode}; schema={settings.required_schema_revision}"))
    google_genai_available = importlib.util.find_spec("google.genai") is not None
    if settings.ares_mode == "local_live":
        results.append(CheckResult("google-genai package", True, google_genai_available, "available" if google_genai_available else "not importable"))
    telemetry = telemetry_export_status(settings.otel_exporter_otlp_endpoint)
    if telemetry["configured"]:
        results.append(CheckResult(
            "optional OTLP exporter", False, telemetry["ready"],
            "available" if telemetry["ready"] else "endpoint configured but optional exporter packages are not installed",
        ))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ARES service/API connectivity without printing secrets.")
    parser.add_argument("--env-file", default=".env", help="settings file to validate")
    parser.add_argument("--network", action="store_true", help="perform bounded read-only network/provider checks")
    parser.add_argument("--require-optional", action="store_true", help="treat optional provider failures as release failures")
    parser.add_argument("--timeout", type=float, default=8.0, help="maximum timeout per connectivity request")
    args = parser.parse_args()

    env_path = Path(args.env_file)
    if not env_path.exists():
        print(f"[FAIL] settings: environment file not found: {env_path}")
        return 2
    try:
        settings = Settings(_env_file=env_path)  # type: ignore[call-arg]
        settings.validate_live_mode()
    except Exception as exc:
        print(f"[FAIL] settings: {type(exc).__name__}: {exc}")
        return 2

    results = _static_checks(settings)
    if args.network:
        timeout = max(1.0, min(float(args.timeout), settings.provider_http_timeout_seconds, 30.0))
        results.extend([
            _db_check(settings),
            _searxng_check(settings, timeout),
            _gemini_check(settings, min(timeout, settings.gemini_timeout_seconds)),
            _oidc_check(settings, timeout),
            _academic_check("OpenAlex", OpenAlexAcademicProvider(settings.openalex_api_key), timeout),
            _academic_check("Crossref", CrossrefAcademicProvider(mailto=settings.crossref_mailto), timeout),
            _academic_check("arXiv", ArxivAcademicProvider(min_interval_seconds=0), timeout),
            _github_check(settings, timeout),
            _jev_check(settings, timeout),
        ])
    else:
        results.append(CheckResult("network checks", False, True, "not requested; pass --network in a service-enabled environment"))

    for result in results:
        _print(result)

    required_failures = [result for result in results if result.required and not result.ok]
    optional_failures = [result for result in results if not result.required and not result.ok]
    if required_failures or (args.require_optional and optional_failures):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
