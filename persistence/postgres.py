from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


DEFAULT_MIGRATIONS_PATH = Path(__file__).resolve().parent / "migrations"
DEFAULT_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def _database_url_from_env_file(env_path: Path, env_var: str) -> str | None:
    if not env_path.exists():
        return None

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != env_var:
            continue
        return value.strip().strip('"').strip("'")

    return None


def database_url_from_env(env_var: str = "DQ_DATABASE_URL") -> str:
    value = os.getenv(env_var)
    if not value:
        value = _database_url_from_env_file(DEFAULT_ENV_PATH, env_var)
    if not value:
        raise RuntimeError(f"{env_var} is required for PostgreSQL-backed DQ storage")
    return value


@contextmanager
def connect(database_url: str | None = None) -> Iterator[object]:
    try:
        import psycopg
    except ModuleNotFoundError as exc:
        raise RuntimeError("Install psycopg[binary] to use PostgreSQL persistence") from exc

    url = database_url or database_url_from_env()
    with psycopg.connect(url) as conn:
        yield conn


def apply_migrations(database_url: str | None = None, migrations_path: str | Path = DEFAULT_MIGRATIONS_PATH) -> list[str]:
    path = Path(migrations_path)
    files = sorted(path.glob("*.sql"))
    if not files:
        raise RuntimeError(f"No migration files found in {path}")

    applied: list[str] = []
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migration (
                    migration_name TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            for migration in files:
                name = migration.name
                cur.execute("SELECT 1 FROM schema_migration WHERE migration_name = %s", (name,))
                if cur.fetchone():
                    continue
                cur.execute(migration.read_text(encoding="utf-8"))
                cur.execute("INSERT INTO schema_migration (migration_name) VALUES (%s)", (name,))
                applied.append(name)
        conn.commit()
    return applied
