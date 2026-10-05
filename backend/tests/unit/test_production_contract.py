from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_database_privilege_groups_keep_public_api_under_rls() -> None:
    sql = (ROOT / "infra/postgres/bootstrap_roles.sql").read_text(encoding="utf-8")
    assert "CREATE ROLE ares_api" in sql and "NOBYPASSRLS" in sql
    assert "CREATE ROLE ares_worker" in sql and "BYPASSRLS" in sql
    assert "GRANT EXECUTE ON FUNCTION ares_global_active_run_count() TO ares_api" in sql
    assert "GRANT SELECT ON worker_instances, alembic_version TO ares_api" in sql
    assert "ALTER DEFAULT PRIVILEGES" not in sql


def test_production_container_is_non_root_and_compose_splits_data_from_egress() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "infra/production/compose.yaml").read_text(encoding="utf-8")
    assert "USER ares:ares" in dockerfile
    assert "cap_drop: [\"ALL\"]" in compose
    assert "no-new-privileges:true" in compose
    assert "data:\n    internal: true" in compose
    assert "networks: [data, egress]" in compose
    postgres_block = compose.split("  postgres:", 1)[1].split("\n  searxng:", 1)[0]
    assert "networks: [data]" in postgres_block
    assert "egress" not in postgres_block


def test_browser_overlay_keeps_chromium_off_app_data_and_host_ports() -> None:
    overlay = (ROOT / "infra/production/compose.browser.yaml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "services/browser/Dockerfile").read_text(encoding="utf-8")
    assert "USER pwuser" in dockerfile
    browser_block = overlay.split("  browser:", 1)[1].split("\nnetworks:", 1)[0]
    assert "env_file:" not in browser_block
    assert "volumes:" not in browser_block
    assert "ports:" not in browser_block
    assert "cap_drop: [\"ALL\"]" in browser_block
    assert "no-new-privileges:true" in browser_block
    assert "seccomp=../browser/seccomp_profile.json" in browser_block
    assert "browser-control" in browser_block and "browser-egress" in browser_block
    assert "data" not in browser_block
    assert "blob-data" not in browser_block
    assert "docker.sock" not in browser_block


def test_seccomp_vendor_script_pins_same_playwright_version_as_browser_image() -> None:
    script = (ROOT / "scripts/vendor_playwright_seccomp.py").read_text(encoding="utf-8")
    dockerfile = (ROOT / "services/browser/Dockerfile").read_text(encoding="utf-8")
    requirements = (ROOT / "services/browser/requirements.txt").read_text(encoding="utf-8")
    assert 'PLAYWRIGHT_VERSION = "v1.63.0"' in script
    assert "playwright/python:v1.63.0-noble" in dockerfile
    assert "playwright==1.63.0" in requirements
    assert "fddc05fb520affb145404e6f6f647ca96af8087d" in script
