"""Tenant context management for Row Level Security (RLS) enforcement."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    import psycopg


def set_tenant_context(conn: psycopg.Connection, tenant_id: UUID | str) -> None:
    """Set app.current_tenant_id scoped to the current transaction."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT set_config(%s, %s, true);",
            ("app.current_tenant_id", str(tenant_id)),
        )


def clear_tenant_context(conn: psycopg.Connection) -> None:
    """Clear app.current_tenant_id in the current transaction."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT set_config(%s, '', true);",
            ("app.current_tenant_id",),
        )


def set_retention_janitor_context(conn: psycopg.Connection) -> None:
    """Set app.retention_execution authorized context for WORM pruning."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT set_config(%s, 'AUTHORIZED_RETENTION_JANITOR', true);",
            ("app.retention_execution",),
        )


@contextmanager
def tenant_context(
    conn: psycopg.Connection, tenant_id: UUID | str
) -> Iterator[psycopg.Connection]:
    """Context manager setting local transaction-scoped tenant ID and resetting on exit."""
    set_tenant_context(conn, tenant_id)
    try:
        yield conn
    finally:
        clear_tenant_context(conn)
