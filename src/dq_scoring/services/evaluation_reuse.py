"""Reuse of an already completed, published evaluation with identical semantic identity."""

from __future__ import annotations

from uuid import UUID

import psycopg

from dq_scoring.common.evaluation_identity import evaluation_fingerprint
from dq_scoring.common.profiling import ProfileRequiredError
from dq_scoring.core.entities import RunSpec
from dq_scoring.services.snapshot_profile_service import (
    profile_fingerprint,
    require_full_profile,
)


def pin_full_profile(conn: psycopg.Connection, spec: RunSpec) -> RunSpec:
    """Require a current COMPLETE FULL profile and return the spec carrying its id and fingerprint."""
    profile = require_full_profile(conn, spec.tenant_id, spec.snapshot.snapshot_id)
    if spec.snapshot.tenant_id != spec.tenant_id or profile_fingerprint(conn, spec.snapshot) != profile["fingerprint"]:
        raise ProfileRequiredError({"state": "STALE"})
    return spec.model_copy(update={"profile_id": profile["profile_id"], "profile_fingerprint": profile["fingerprint"]})


def find_reusable_run(conn: psycopg.Connection, spec: RunSpec) -> UUID | None:
    """Latest SUCCEEDED run of the same tenant and owner with a PUBLISHED assessment and identical fingerprint."""
    if spec.created_by is None:
        return None
    pinned = pin_full_profile(conn, spec)
    fingerprint = evaluation_fingerprint(pinned, profile_fingerprint=pinned.profile_fingerprint)
    row = conn.execute(
        """
        SELECT r.run_id FROM evaluation_runs r
        JOIN assessments a ON a.tenant_id = r.tenant_id AND a.run_id = r.run_id
        WHERE r.tenant_id = %s AND r.created_by = %s AND r.snapshot_id = %s
          AND r.evaluation_fingerprint = %s AND r.run_status = 'SUCCEEDED'
          AND a.publication_status = 'PUBLISHED'
        ORDER BY r.completed_at DESC, r.run_id DESC LIMIT 1;
        """,
        (spec.tenant_id, spec.created_by, spec.snapshot.snapshot_id, fingerprint),
    ).fetchone()
    return row[0] if row else None
