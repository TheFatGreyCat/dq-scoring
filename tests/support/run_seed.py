"""Test-only seeding of the rows a run references (tenant, user, asset, snapshot, ruleset, policy)."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from dq_scoring.adapters.db.tenant_context import set_tenant_context
from dq_scoring.common.hash_utils import compute_deterministic_hash
from dq_scoring.common.profiling import PROFILER_VERSION, ColumnProfile, SnapshotProfile
from dq_scoring.core.entities import DatasetSnapshot, RunSpec
from dq_scoring.services.snapshot_profile_service import (
    load_snapshot,
    profile_fingerprint,
)


def synthetic_full_profile(
    snapshot: DatasetSnapshot, *, profile_id: UUID | None = None, fingerprint: str | None = None
) -> SnapshotProfile:
    """Validated FULL profile for a known synthetic fixture: no nulls, distinct unknown.

    Only for fixtures where the profile gate is not under test; real FULL evidence comes from the Spark worker.
    """
    columns = []
    for definition in snapshot.schema_definition.get("columns", []):
        definition = {"name": definition} if isinstance(definition, str) else definition
        target = definition.get("parse_target")
        columns.append(
            ColumnProfile(
                name=definition["name"],
                technical_type=definition.get("type", "STRING").upper(),
                null_count=0,
                non_null_count=snapshot.total_rows,
                distinct_reason="UNSUPPORTED_TYPE",
                parse_success_count=snapshot.total_rows if target else None,
                parse_target=target,
                parse_format=definition.get("parse_format"),
                parse_reason=None if target else "NO_EXPLICIT_TARGET",
            )
        )
    return SnapshotProfile(
        mode="FULL",
        profiler_version=PROFILER_VERSION,
        profile_id=profile_id or uuid4(),
        fingerprint=fingerprint or sha256(str(snapshot.snapshot_id).encode()).hexdigest(),
        generated_at=datetime.now(UTC),
        total_rows=snapshot.total_rows,
        scanned_rows=snapshot.total_rows,
        is_sample=False,
        sampling_method="EXACT",
        columns=tuple(columns),
    )


def _seed_full_profile(conn: psycopg.Connection, tenant_id: UUID, snapshot_id: UUID) -> None:
    """Publish a synthetic COMPLETE job through the real lease transitions (superuser seed connection)."""
    snapshot = load_snapshot(conn, tenant_id, snapshot_id)
    fingerprint = profile_fingerprint(conn, snapshot)
    row = conn.execute(
        "INSERT INTO snapshot_profile_jobs(tenant_id,snapshot_id,fingerprint,profiler_version) VALUES(%s,%s,%s,%s) "
        "ON CONFLICT(tenant_id,snapshot_id,fingerprint) DO NOTHING RETURNING profile_id",
        (tenant_id, snapshot_id, fingerprint, PROFILER_VERSION),
    ).fetchone()
    if row is None:
        return
    profile = synthetic_full_profile(snapshot, profile_id=row[0], fingerprint=fingerprint)
    conn.execute(
        "UPDATE snapshot_profile_jobs SET state='RUNNING',lease_owner='seed',lease_generation=1,attempt_count=1,"
        "started_at=clock_timestamp(),heartbeat_at=clock_timestamp(),lease_expires_at=clock_timestamp()+interval '1 hour' "
        "WHERE profile_id=%s",
        (row[0],),
    )
    conn.execute(
        "UPDATE snapshot_profile_jobs SET state='COMPLETE',result=%s,finished_at=clock_timestamp() WHERE profile_id=%s",
        (Jsonb(profile.model_dump(mode="json")), row[0]),
    )


def seed_run_prerequisites(dsn: str, spec: RunSpec, *, profile_ready: bool = True) -> RunSpec:
    """Insert approved configuration for `spec` and return it with resolved IDs.

    `profile_ready=True` adds a validated synthetic COMPLETE FULL profile for the snapshot only when it has no
    current profile job; use False (or a real worker-registered snapshot) when the gate itself is under test.
    """
    with psycopg.connect(dsn) as conn, conn.transaction():
        set_tenant_context(conn, spec.tenant_id)
        with conn.cursor() as cur:
            user_id = spec.created_by or uuid4()
            ruleset_id = spec.ruleset_id or (
                spec.rules[0].ruleset_id
                if spec.rules and spec.rules[0].ruleset_id
                else uuid4()
            )
            target_policy_id = spec.policy_id or (
                spec.policy.policy_id if spec.policy and spec.policy.policy_id else None
            )
            if target_policy_id:
                policy_id = target_policy_id
            else:
                cur.execute(
                    "SELECT policy_id FROM scoring_policies WHERE tenant_id = %s AND status = 'ACTIVE' LIMIT 1;",
                    (spec.tenant_id,),
                )
                pol_row = cur.fetchone()
                policy_id = pol_row[0] if pol_row else uuid4()

            cur.execute(
                """
                INSERT INTO tenants (tenant_id, tenant_code, tenant_name)
                VALUES (%s, %s, %s)
                ON CONFLICT (tenant_id) DO NOTHING;
                """,
                (
                    spec.tenant_id,
                    f"tenant-{spec.tenant_id}",
                    f"Tenant {spec.tenant_id}",
                ),
            )

            cur.execute(
                """
                INSERT INTO users (user_id, email, password_hash, full_name)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING;
                """,
                (
                    user_id,
                    f"user-{user_id}@dqscoring.local",
                    "$argon2id$seedhash",
                    f"User {user_id}",
                ),
            )

            cur.execute(
                """
                INSERT INTO data_assets (
                    asset_id, tenant_id, asset_name, slug, format,
                    owner_user_id, created_by
                ) VALUES (%s, %s, %s, %s, 'CSV', %s, %s)
                ON CONFLICT (tenant_id, asset_id) DO NOTHING;
                """,
                (
                    spec.snapshot.asset_id,
                    spec.tenant_id,
                    f"Asset {spec.snapshot.asset_id}",
                    f"asset-{spec.snapshot.asset_id}",
                    user_id,
                    user_id,
                ),
            )

            raw_descriptor = spec.snapshot.source_descriptor
            if raw_descriptor.get("descriptor_version") == 2:
                source_desc = raw_descriptor
                storage_loc = f"s3a://{raw_descriptor['bucket']}/{raw_descriptor['key']}"
            else:
                canonical_info = raw_descriptor.get("canonical")
                if not isinstance(canonical_info, dict) or canonical_info.get("format") != "PARQUET":
                    canonical_info = {
                        "bucket": "dq-snapshots-local",
                        "key": f"snapshots/{spec.tenant_id}/{spec.snapshot.snapshot_id}/canonical.parquet",
                        "version_id": "v1",
                        "s3a_uri": f"s3a://dq-snapshots-local/snapshots/{spec.tenant_id}/{spec.snapshot.snapshot_id}/canonical.parquet",
                        "content_sha256": raw_descriptor.get("content_sha256", "0" * 64),
                        "size_bytes": 1024,
                        "format": "PARQUET",
                    }
                source_desc = {
                    **raw_descriptor,
                    "canonical": canonical_info,
                    "normalization_version": raw_descriptor.get("normalization_version", 1),
                }
                storage_loc = (
                    canonical_info.get("s3a_uri")
                    or raw_descriptor.get("path")
                    or f"s3a://staging/{spec.snapshot.snapshot_id}"
                )
            source_kind = "OBJECT_FILE"
            cur.execute(
                """
                INSERT INTO dataset_snapshots (
                    snapshot_id, tenant_id, asset_id, version_number,
                    source_kind, source_descriptor, content_sha256,
                    storage_location, schema_definition, total_rows, total_columns,
                    created_by, captured_at
                ) VALUES (%s, %s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, snapshot_id) DO NOTHING;
                """,
                (
                    spec.snapshot.snapshot_id,
                    spec.tenant_id,
                    spec.snapshot.asset_id,
                    source_kind,
                    Jsonb(source_desc),
                    spec.snapshot.source_descriptor.get("content_sha256", "a" * 64),
                    storage_loc,
                    Jsonb(spec.snapshot.schema_definition),
                    spec.snapshot.total_rows,
                    spec.snapshot.total_columns,
                    user_id,
                    spec.snapshot.captured_at,
                ),
            )

            ruleset_hash = compute_deterministic_hash(
                {"rules": [r.model_dump(mode="json") for r in spec.rules]}
            )
            cur.execute(
                """
                INSERT INTO rulesets (
                    ruleset_id, tenant_id, asset_id, version, config_hash,
                    status, created_by, submitted_by, submitted_at, approved_by, approved_at
                ) VALUES (%s, %s, %s, %s, %s, 'ACTIVE', %s, %s, now(), %s, now())
                ON CONFLICT (tenant_id, ruleset_id) DO NOTHING;
                """,
                (
                    ruleset_id,
                    spec.tenant_id,
                    spec.snapshot.asset_id,
                    f"ruleset-{ruleset_id}",
                    ruleset_hash,
                    user_id,
                    user_id,
                    user_id,
                ),
            )

            for rule in spec.rules:
                target_col = rule.parameters.get(
                    "column", rule.parameters.get("target_column", "*")
                )
                score_enabled = False if rule.is_advisory else rule.score_enabled
                weight = 0.0 if rule.is_advisory else rule.contribution_weight
                cur.execute(
                    """
                    INSERT INTO quality_rules (
                        rule_id, tenant_id, ruleset_id, rule_name, dimension,
                        target_column, rule_type, parameters, null_policy, weight, severity,
                        is_advisory, is_required, gate_enabled, score_enabled,
                        acceptance_threshold, conflict_group, is_primary_scoring_rule, source
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, 'USER'
                    ) ON CONFLICT (tenant_id, rule_id) DO NOTHING;
                    """,
                    (
                        rule.rule_id,
                        spec.tenant_id,
                        ruleset_id,
                        rule.rule_code,
                        rule.dimension.upper(),
                        target_col,
                        rule.rule_type.upper(),
                        Jsonb(rule.parameters),
                        rule.null_policy.upper(),
                        weight,
                        "CRITICAL" if rule.is_critical else "STANDARD",
                        rule.is_advisory,
                        rule.is_required,
                        rule.gate_enabled,
                        score_enabled,
                        rule.acceptance_threshold,
                        rule.conflict_group,
                        rule.is_primary_scoring_rule,
                    ),
                )

            cur.execute(
                "SELECT 1 FROM scoring_policies WHERE tenant_id = %s AND policy_id = %s;",
                (spec.tenant_id, policy_id),
            )
            if not cur.fetchone():
                pol_hash = compute_deterministic_hash(spec.policy.model_dump(mode="json"))
                cur.execute(
                    """
                    INSERT INTO scoring_policies (
                        policy_id, tenant_id, version, config_hash, status,
                        created_by, submitted_by, submitted_at, approved_by, approved_at,
                        dimension_weights, publication_threshold, gate_rules
                    ) VALUES (%s, %s, %s, %s, 'ACTIVE', %s, %s, now(), %s, now(), %s, %s, %s)
                    ON CONFLICT (tenant_id, policy_id) DO NOTHING;
                    """,
                    (
                        policy_id,
                        spec.tenant_id,
                        f"policy-{policy_id}",
                        pol_hash,
                        user_id,
                        user_id,
                        user_id,
                        Jsonb(spec.policy.dimension_weights),
                        spec.policy.publication_threshold,
                        Jsonb(
                            {
                                "gate_fail_threshold": spec.policy.warn_min,
                                "gate_warn_threshold": spec.policy.pass_min,
                                "critical_acceptance_threshold": spec.policy.critical_acceptance_threshold,
                            }
                        ),
                    ),
                )

        if profile_ready:
            _seed_full_profile(conn, spec.tenant_id, spec.snapshot.snapshot_id)

    new_snapshot = spec.snapshot.model_copy(update={"source_kind": "OBJECT_FILE", "source_descriptor": source_desc})
    return spec.model_copy(
        update={
            "ruleset_id": ruleset_id,
            "policy_id": policy_id,
            "created_by": user_id,
            "snapshot": new_snapshot,
        }
    )
