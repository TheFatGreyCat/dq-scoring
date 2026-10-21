"""Audit pre-release migration 023; rebuild only empty legacy semantic tables.

Dry-run is the default. The administrative DSN is read only from the environment.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Literal

import psycopg
from psycopg import sql

from dq_scoring.adapters.db.migrator import DEFAULT_MIGRATIONS_DIR

SEMANTIC_TABLES = (
    "snapshot_semantic_state",
    "snapshot_column_semantics",
    "snapshot_column_semantic_history",
)
EXPECTED_TRIGGERS: dict[str, str] = {
    "semantic_revision_guard": "snapshot_semantic_state",
    "semantic_history_guard": "snapshot_column_semantic_history",
    "no_semantic_history_update": "snapshot_column_semantic_history",
    "semantic_projection_guard": "snapshot_column_semantics",
    "semantic_state_history_required": "snapshot_semantic_state",
    "semantic_projection_history_required": "snapshot_column_semantics",
}
EXPECTED_FUNCTIONS = (
    "enforce_semantic_revision",
    "enforce_semantic_history",
    "enforce_semantic_projection",
    "check_semantic_commit",
)


class RepairAborted(Exception):
    """Fixed, credential-free operator status."""

    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


def schema_state(conn: psycopg.Connection) -> Literal["ABSENT", "CURRENT", "LEGACY"]:
    tables = {row[0] for row in conn.execute(
        "SELECT c.relname FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relkind IN ('r','p') AND c.relname=ANY(%s)", (list(SEMANTIC_TABLES),)
    )}
    if not tables:
        return "ABSENT"
    if tables != set(SEMANTIC_TABLES):
        raise RepairAborted("SEMANTIC_SCHEMA_PARTIAL")
    triggers = dict(conn.execute(
        "SELECT t.tgname,c.relname FROM pg_catalog.pg_trigger t "
        "JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND NOT t.tgisinternal AND t.tgenabled IN ('O','A') AND t.tgname=ANY(%s)",
        (list(EXPECTED_TRIGGERS),)
    ).fetchall())
    functions = {row[0] for row in conn.execute(
        "SELECT p.proname FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='public' AND p.pronargs=0 AND p.prorettype='pg_catalog.trigger'::regtype AND p.proname=ANY(%s)",
        (list(EXPECTED_FUNCTIONS),)
    )}
    return "CURRENT" if triggers == EXPECTED_TRIGGERS and functions == set(EXPECTED_FUNCTIONS) else "LEGACY"


def row_counts(conn: psycopg.Connection) -> dict[str, int]:
    conn.execute("SET LOCAL row_security=off")
    return {table: conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier("public", table))).fetchone()[0]
            for table in SEMANTIC_TABLES}


def repair(conn: psycopg.Connection, migrations_dir: Path = DEFAULT_MIGRATIONS_DIR) -> str:
    with conn.transaction():
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute("SET LOCAL row_security=off")
        conn.execute("SET LOCAL search_path=public,pg_catalog")
        state = schema_state(conn)
        if state == "ABSENT":
            return state
        conn.execute(sql.SQL("LOCK TABLE {} IN ACCESS EXCLUSIVE MODE").format(
            sql.SQL(", ").join(sql.Identifier("public", table) for table in SEMANTIC_TABLES)))
        state = schema_state(conn)
        if state != "LEGACY":
            return state
        if any(row_counts(conn).values()):
            raise RepairAborted("SEMANTIC_EVIDENCE_NOT_EMPTY")
        for table in reversed(SEMANTIC_TABLES):
            conn.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier("public", table)))
        for function in EXPECTED_FUNCTIONS:
            conn.execute(sql.SQL("DROP FUNCTION IF EXISTS {}()").format(sql.Identifier("public", function)))
        conn.execute((migrations_dir / "023_column_semantics.sql").read_text(encoding="utf-8"))
        if schema_state(conn) != "CURRENT":
            raise RepairAborted("SEMANTIC_REPAIR_VERIFICATION_FAILED")
        return "CURRENT"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Rebuild only empty legacy semantic tables")
    args = parser.parse_args()
    dsn = os.environ.get("DQ_ADMIN_POSTGRES_DSN")
    if not dsn:
        print("DQ_ADMIN_POSTGRES_DSN_REQUIRED")
        return 1
    try:
        with psycopg.connect(dsn) as conn, conn.transaction():
            state = repair(conn) if args.apply else schema_state(conn)
            print(json.dumps({"state": state, "rows": row_counts(conn) if state != "ABSENT" else {}}))
    except RepairAborted as error:
        print(error.status)
        return 2
    except (psycopg.Error, OSError):
        print("SEMANTIC_REPAIR_FAILED")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
