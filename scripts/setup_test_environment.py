"""Prepare and provision the isolated synthetic E2E environment (compose project dq-e2e-test).

  uv run --locked python scripts/setup_test_environment.py --prepare-env
  docker compose --env-file .tmp/e2e.env -p dq-e2e-test -f deploy/compose/test.yml up -d --wait
  uv run --locked python scripts/setup_test_environment.py --provision

Secrets are generated here, stored only in .tmp/e2e.env (0600) and never printed or passed on argv.
"""

from __future__ import annotations

import argparse
import os
import secrets
import stat
import sys
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".tmp" / "e2e.env"
PG_ADDR = ("127.0.0.1", 15432)
S3_ENDPOINT = "http://127.0.0.1:19000"
TEST_DB = "dq_scoring_test"  # truncated by the pytest fixtures
RUNTIME_DB = "dq_e2e_runtime"  # API/worker runtime for browser acceptance, never truncated
APP_USER = "dq_e2e_app"
WORKER_USER = "dq_e2e_worker"
READY_TIMEOUT_SECONDS = 60


def _token() -> str:
    return secrets.token_hex(24)


def _pg_dsn(user: str, password: str, db: str) -> str:
    return f"postgresql://{user}:{password}@{PG_ADDR[0]}:{PG_ADDR[1]}/{db}"


def _generate(existing: dict[str, str]) -> dict[str, str]:
    """Return every required key; existing values win so re-runs keep the provisioned state."""
    run_id = existing.get("DQ_E2E_RUN_ID") or secrets.token_hex(4)
    admin_pw = existing.get("DQ_TEST_DB_PASSWORD") or _token()
    app_pw = existing.get("DQ_E2E_APP_DB_PASSWORD") or _token()
    worker_pw = existing.get("DQ_E2E_WORKER_DB_PASSWORD") or _token()
    s3_key = existing.get("DQ_TEST_S3_ACCESS_KEY") or f"dqe2e{secrets.token_hex(8)}"
    s3_secret = existing.get("DQ_TEST_S3_SECRET_KEY") or _token()
    jwt = existing.get("DQ_AUTH_SECRET_KEY") or secrets.token_hex(32)
    return {
        "DQ_E2E_RUN_ID": run_id,
        "DQ_TEST_DB_PASSWORD": admin_pw,
        "DQ_E2E_APP_DB_PASSWORD": app_pw,
        "DQ_E2E_WORKER_DB_PASSWORD": worker_pw,
        "DQ_TEST_S3_ACCESS_KEY": s3_key,
        "DQ_TEST_S3_SECRET_KEY": s3_secret,
        "DQ_APP_ENV": "development",
        "DQ_AUTH_ALGORITHM": "HS256",
        "DQ_AUTH_SECRET_KEY": jwt,
        "DQ_TEST_POSTGRES_DSN": _pg_dsn("dq_test_admin", admin_pw, TEST_DB),
        "DQ_POSTGRES_DSN": _pg_dsn(APP_USER, app_pw, RUNTIME_DB),
        "DQ_WORKER_POSTGRES_DSN": _pg_dsn(WORKER_USER, worker_pw, RUNTIME_DB),
        "DQ_S3_ENDPOINT_URL": S3_ENDPOINT,
        # ponytail: app uses the disposable MinIO root user; scoped MinIO users if tests must prove bucket policies.
        "DQ_S3_ACCESS_KEY_ID": s3_key,
        "DQ_S3_SECRET_ACCESS_KEY": s3_secret,
        "DQ_S3_REGION": "us-east-1",
        "DQ_S3_USE_SSL": "false",
        "DQ_S3_BUCKET_STAGING": f"dq-e2e-{run_id}-staging",
        "DQ_S3_BUCKET_SNAPSHOTS": f"dq-e2e-{run_id}-snapshots",
        "DQ_S3_BUCKET_ARTIFACTS": f"dq-e2e-{run_id}-artifacts",
        "DQ_IMPORT_TEMP_ROOT": ".tmp/e2e-imports",
        "DQ_SPARK_MASTER": "local[*]",
    }


def _check_private(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        sys.exit(f"{path} must be a regular file owned by the current user; refusing to use it.")
    if info.st_mode & 0o077:
        sys.exit(f"{path} is readable by other users; run: chmod 600 {path}")


def _read_env(path: Path) -> dict[str, str]:
    _check_private(path)
    pairs = (line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line)
    return {key.strip(): value.strip() for key, value in pairs if not key.lstrip().startswith("#")}


def prepare_env() -> None:
    ENV_FILE.parent.mkdir(mode=0o700, exist_ok=True)
    is_present = ENV_FILE.is_symlink() or ENV_FILE.exists()
    existing = _read_env(ENV_FILE) if is_present else {}
    missing = {key: value for key, value in _generate(existing).items() if key not in existing}
    if not missing:
        print(f"{ENV_FILE.relative_to(ROOT)} is complete; nothing changed.")
        return
    flags = os.O_WRONLY | os.O_NOFOLLOW | (os.O_APPEND if is_present else os.O_CREAT | os.O_EXCL)
    needs_newline = is_present and not ENV_FILE.read_bytes().endswith(b"\n") and ENV_FILE.stat().st_size > 0
    with os.fdopen(os.open(ENV_FILE, flags, 0o600), "a", encoding="utf-8") as handle:
        if not is_present:
            handle.write("# Synthetic dq-e2e-test credentials. Generated; never commit or reuse.\n")
        if needs_newline:
            handle.write("\n")
        handle.writelines(f"{key}={value}\n" for key, value in missing.items())
    print(f"Wrote {len(missing)} keys to {ENV_FILE.relative_to(ROOT)} (0600): {', '.join(sorted(missing))}")


def _require_isolated(env: dict[str, str]) -> None:
    """Refuse to touch anything except the loopback dq-e2e-test services."""
    for key in ("DQ_TEST_POSTGRES_DSN", "DQ_POSTGRES_DSN", "DQ_WORKER_POSTGRES_DSN"):
        parts = urlsplit(env[key])
        if (parts.hostname, parts.port) != PG_ADDR or parts.path.lstrip("/") not in (TEST_DB, RUNTIME_DB):
            sys.exit(f"{key} does not target the isolated test PostgreSQL; refusing to provision.")
    if env["DQ_S3_ENDPOINT_URL"] != S3_ENDPOINT:
        sys.exit("DQ_S3_ENDPOINT_URL does not target the isolated test MinIO; refusing to provision.")
    if not all(env[f"DQ_S3_BUCKET_{name}"].startswith("dq-e2e-") for name in ("STAGING", "SNAPSHOTS", "ARTIFACTS")):
        sys.exit("Test buckets must use the dq-e2e- prefix; refusing to provision.")


def _wait_for[T](name: str, attempt: Callable[[], T]) -> T:
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while True:
        try:
            return attempt()
        except Exception as exc:  # noqa: BLE001 - only the exception type is reported, never connection details
            if time.monotonic() > deadline:
                sys.exit(f"{name} not reachable after {READY_TIMEOUT_SECONDS}s ({type(exc).__name__}); start compose first.")
            time.sleep(2)


def _provision_postgres(env: dict[str, str]) -> None:
    import psycopg
    from psycopg import sql

    from dq_scoring.adapters.db.migrator import apply_all_migrations

    admin_dsn = env["DQ_TEST_POSTGRES_DSN"]
    with _wait_for("PostgreSQL", lambda: psycopg.connect(admin_dsn, autocommit=True)) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (RUNTIME_DB,)).fetchone():
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(RUNTIME_DB)))
    runtime_admin_dsn = admin_dsn.rsplit("/", 1)[0] + f"/{RUNTIME_DB}"
    with psycopg.connect(runtime_admin_dsn) as conn:
        applied = apply_all_migrations(conn)
        # Group roles exist after migrations 001/007; login users only inherit them (no superuser/BYPASSRLS).
        for user, group, password_key in (
            (APP_USER, "dq_app_role", "DQ_E2E_APP_DB_PASSWORD"),
            (WORKER_USER, "dq_worker_role", "DQ_E2E_WORKER_DB_PASSWORD"),
        ):
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (user,)).fetchone()
            verb = "ALTER" if exists else "CREATE"
            conn.execute(
                sql.SQL(verb + " ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD {}").format(
                    sql.Identifier(user), sql.Literal(env[password_key])
                )
            )
            conn.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), sql.Identifier(user)))
        conn.commit()
    print(f"PostgreSQL: {RUNTIME_DB} migrated ({len(applied)} new); login roles {APP_USER}, {WORKER_USER} ready.")


def _provision_minio(env: dict[str, str]) -> None:
    import boto3
    from botocore.config import Config

    s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        region_name=env["DQ_S3_REGION"],
        aws_access_key_id=env["DQ_TEST_S3_ACCESS_KEY"],
        aws_secret_access_key=env["DQ_TEST_S3_SECRET_KEY"],
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 1}),
    )
    existing = {bucket["Name"] for bucket in _wait_for("MinIO", s3.list_buckets)["Buckets"]}
    for name in ("STAGING", "SNAPSHOTS", "ARTIFACTS"):
        bucket = env[f"DQ_S3_BUCKET_{name}"]
        if bucket not in existing:
            s3.create_bucket(Bucket=bucket)
    snapshots = env["DQ_S3_BUCKET_SNAPSHOTS"]
    s3.put_bucket_versioning(Bucket=snapshots, VersioningConfiguration={"Status": "Enabled"})
    if s3.get_bucket_versioning(Bucket=snapshots).get("Status") != "Enabled":
        sys.exit(f"Versioning did not enable on {snapshots}.")
    print(f"MinIO: buckets dq-e2e-{env['DQ_E2E_RUN_ID']}-{{staging,snapshots,artifacts}} ready; snapshots versioned.")


def provision() -> None:
    if not ENV_FILE.exists():
        sys.exit(f"{ENV_FILE.relative_to(ROOT)} missing; run --prepare-env first.")
    env = _read_env(ENV_FILE)
    missing = [key for key in _generate({}) if key not in env]
    if missing:
        sys.exit(f"{ENV_FILE.relative_to(ROOT)} lacks {', '.join(missing)}; run --prepare-env.")
    _require_isolated(env)
    _provision_postgres(env)
    _provision_minio(env)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare-env", action="store_true", help="create/complete .tmp/e2e.env (0600)")
    action.add_argument("--provision", action="store_true", help="migrate runtime DB, create roles and test buckets")
    args = parser.parse_args()
    if args.prepare_env:
        prepare_env()
    else:
        provision()


if __name__ == "__main__":
    main()
