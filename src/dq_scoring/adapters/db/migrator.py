"""Database schema migration runner for PostgreSQL 16."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import psycopg

MIGRATION_FILE_PATTERN = re.compile(r"^(\d+)_(.+)\.sql$")
DOWN_MIGRATION_PATTERN = re.compile(r"^(\d+)_(.+)_down\.sql$")

DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def init_schema_history(conn: psycopg.Connection) -> None:
    """Ensure schema_migrations tracking table exists."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
    conn.commit()


def get_applied_migrations(conn: psycopg.Connection) -> list[str]:
    """Retrieve list of applied migration versions sorted ascending."""
    init_schema_history(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations ORDER BY version ASC;")
        rows = cur.fetchall()
        return [r[0] for r in rows]


def apply_all_migrations(
    conn: psycopg.Connection,
    migrations_dir: Path | str | None = None,
) -> list[str]:
    """Apply all pending migrations in ascending version order."""
    init_schema_history(conn)
    target_dir = Path(migrations_dir) if migrations_dir else DEFAULT_MIGRATIONS_DIR

    applied = set(get_applied_migrations(conn))
    candidates: list[tuple[str, str, Path]] = []

    for file in target_dir.iterdir():
        if file.is_file() and not file.name.endswith("_down.sql"):
            match = MIGRATION_FILE_PATTERN.match(file.name)
            if match:
                version, name = match.group(1), match.group(2)
                candidates.append((version, name, file))

    candidates.sort(key=lambda x: x[0])
    newly_applied: list[str] = []

    for version, name, file_path in candidates:
        if version not in applied:
            sql_content = file_path.read_text(encoding="utf-8")
            with conn.transaction(), conn.cursor() as cur:
                cur.execute(sql_content)
                cur.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES (%s, %s);",
                    (version, name),
                )
            newly_applied.append(version)

    return newly_applied


def rollback_last_migration(
    conn: psycopg.Connection,
    migrations_dir: Path | str | None = None,
) -> str | None:
    """Roll back the last applied migration using its down script."""
    init_schema_history(conn)
    applied = get_applied_migrations(conn)
    if not applied:
        return None

    last_version = applied[-1]
    target_dir = Path(migrations_dir) if migrations_dir else DEFAULT_MIGRATIONS_DIR

    down_file: Path | None = None
    for file in target_dir.iterdir():
        if file.is_file():
            match = DOWN_MIGRATION_PATTERN.match(file.name)
            if match and match.group(1) == last_version:
                down_file = file
                break

    if down_file is None:
        raise FileNotFoundError(
            f"No down migration script found for version {last_version}"
        )

    down_sql = down_file.read_text(encoding="utf-8")
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(down_sql)
        cur.execute(
            "DELETE FROM schema_migrations WHERE version = %s;",
            (last_version,),
        )

    return last_version
