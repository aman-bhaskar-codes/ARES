"""Provision concrete PostgreSQL LOGIN roles without printing credentials.

Run after Alembic 0006+ and infra/postgres/bootstrap_roles.sql. This script is
intentionally explicit and idempotent; it does not grant superuser/createdb/createrole.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

import psycopg
from psycopg import sql


def required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def ensure_login(conn: psycopg.Connection, name: str, password: str, group: str) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (name,))
        if cur.fetchone():
            cur.execute(
                sql.SQL("ALTER ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD %s").format(
                    sql.Identifier(name)
                ),
                (password,),
            )
        else:
            cur.execute(
                sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD %s").format(
                    sql.Identifier(name)
                ),
                (password,),
            )
        cur.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), sql.Identifier(name)))


def main() -> int:
    admin_url = required("MIGRATION_DATABASE_URL")
    api_user = os.environ.get("ARES_API_DB_USER", "ares_api_login")
    worker_user = os.environ.get("ARES_WORKER_DB_USER", "ares_worker_login")
    api_password = required("ARES_API_DB_PASSWORD")
    worker_password = required("ARES_WORKER_DB_PASSWORD")
    if api_user == worker_user:
        raise SystemExit("API and worker database users must be distinct")
    with psycopg.connect(admin_url, autocommit=True) as conn:
        ensure_login(conn, api_user, api_password, "ares_api")
        ensure_login(conn, worker_user, worker_password, "ares_worker")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = ANY(%s) ORDER BY rolname",
                ([api_user, worker_user],),
            )
            rows = cur.fetchall()
    if len(rows) != 2 or any(row[1] for row in rows) or any(row[2] for row in rows):
        raise SystemExit("concrete LOGIN roles must be non-superuser and must not directly BYPASSRLS")
    print(f"Provisioned API/worker LOGIN roles for database host {urlsplit(admin_url).hostname or 'local'}; credentials were not printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
