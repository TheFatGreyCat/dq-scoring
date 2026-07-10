from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from persistence.postgres import connect, database_url_from_env
from persistence.repository import DEFAULT_UPLOAD_DIR


def get_system_health(database_url: str | None = None, upload_dir: str | Path = DEFAULT_UPLOAD_DIR) -> dict[str, Any]:
    resolved_url = _resolve_database_url(database_url)
    config = _database_config(resolved_url)
    health: dict[str, Any] = {
        "postgresql": {
            "status": "not_configured" if not resolved_url else "unreachable",
            "database": config["database"],
            "host": config["host"],
            "error": None,
        },
        "schema": {
            "status": "unknown",
            "migration_table": False,
            "latest_migration": None,
            "migration_count": 0,
        },
        "rule_catalog": {
            "status": "unknown",
            "template_count": 0,
        },
        "runtime_storage": _storage_status(upload_dir),
        "local_llm": {
            "status": "not_configured",
            "provider": None,
        },
    }
    if not resolved_url:
        health["postgresql"]["error"] = "DQ_DATABASE_URL is not configured"
        return health

    try:
        with connect(_with_connect_timeout(resolved_url)) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database()")
                row = cur.fetchone()
                if row and row[0]:
                    health["postgresql"]["database"] = str(row[0])
                health["postgresql"]["status"] = "reachable"

                cur.execute("SELECT to_regclass('public.schema_migration')")
                has_migration_table = cur.fetchone()[0] is not None
                health["schema"]["migration_table"] = bool(has_migration_table)
                if has_migration_table:
                    cur.execute("SELECT migration_name FROM schema_migration ORDER BY applied_at DESC, migration_name DESC LIMIT 1")
                    latest = cur.fetchone()
                    cur.execute("SELECT count(*) FROM schema_migration")
                    count = cur.fetchone()[0]
                    health["schema"].update(
                        {
                            "status": "ready",
                            "latest_migration": latest[0] if latest else None,
                            "migration_count": int(count or 0),
                        }
                    )
                else:
                    health["schema"]["status"] = "migration_required"

                cur.execute("SELECT to_regclass('public.rule_template')")
                has_rule_template = cur.fetchone()[0] is not None
                if has_rule_template:
                    cur.execute("SELECT count(*) FROM rule_template WHERE active = true")
                    template_count = int(cur.fetchone()[0] or 0)
                    health["rule_catalog"].update(
                        {
                            "status": "ready" if template_count else "empty",
                            "template_count": template_count,
                        }
                    )
                else:
                    health["rule_catalog"]["status"] = "migration_required"
    except Exception as exc:
        health["postgresql"]["error"] = str(exc)

    return health


def _resolve_database_url(database_url: str | None) -> str | None:
    if database_url:
        return database_url
    try:
        return database_url_from_env()
    except Exception:
        return None


def _database_config(database_url: str | None) -> dict[str, str | None]:
    if not database_url:
        return {"database": None, "host": None}
    parsed = urlparse(database_url)
    host = parsed.hostname or "configured"
    if parsed.port:
        host = f"{host}:{parsed.port}"
    database = parsed.path.lstrip("/") or None
    return {"database": database, "host": host}


def _with_connect_timeout(database_url: str, timeout_seconds: int = 3) -> str:
    parsed = urlparse(database_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault("connect_timeout", str(timeout_seconds))
    return urlunparse(parsed._replace(query=urlencode(query)))


def _storage_status(upload_dir: str | Path) -> dict[str, Any]:
    path = Path(upload_dir)
    existing_path = path if path.exists() else path.parent
    return {
        "status": "ready" if existing_path.exists() and os.access(existing_path, os.W_OK) else "not_writable",
        "path": str(path),
        "exists": path.exists(),
        "writable": existing_path.exists() and os.access(existing_path, os.W_OK),
    }

