"""Test-only synthetic tenants, users and runs for job-visibility contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from dq_scoring.presentation.api.auth import hash_password

PASSWORD = "SyntheticPassword123!"


@dataclass
class Workspace:
    tenant_id: UUID
    snapshot_id: UUID
    ruleset_id: UUID
    policy_id: UUID
    asset_id: UUID
    users: dict[str, UUID] = field(default_factory=dict)
    emails: dict[str, str] = field(default_factory=dict)


def seed_workspace(db_conn, roles: dict[str, str]) -> Workspace:
    """Create a tenant with one user per `name -> role` plus approved snapshot/ruleset/policy."""
    tenant_id = uuid4()
    ws = Workspace(tenant_id, uuid4(), uuid4(), uuid4(), uuid4())
    pwd_hash = hash_password(PASSWORD)
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tenants (tenant_id, tenant_code, tenant_name, subscription_tier, status) "
            "VALUES (%s, %s, 'Synthetic Org', 'ENTERPRISE', 'ACTIVE');",
            (tenant_id, f"org_{tenant_id.hex[:10]}"),
        )
        for name, role in roles.items():
            uid = uuid4()
            ws.users[name] = uid
            ws.emails[name] = f"{name}_{uid.hex[:8]}@example.test"
            cur.execute(
                "INSERT INTO users (user_id, email, password_hash, full_name, is_active) "
                "VALUES (%s, %s, %s, 'Synthetic User', TRUE);",
                (uid, ws.emails[name], pwd_hash),
            )
            cur.execute(
                "INSERT INTO tenant_memberships (tenant_id, user_id, role, status) VALUES (%s, %s, %s, 'ACTIVE');",
                (tenant_id, uid, role),
            )
        owner = next(iter(ws.users.values()))
        cur.execute(
            "INSERT INTO data_assets (asset_id, tenant_id, asset_name, slug, format, owner_user_id, created_by) "
            "VALUES (%s, %s, 'Synthetic asset', %s, 'CSV', %s, %s);",
            (ws.asset_id, tenant_id, uuid4().hex, owner, owner),
        )
        cur.execute(
            """
            INSERT INTO dataset_snapshots (
                snapshot_id, tenant_id, asset_id, version_number, source_kind, source_descriptor,
                content_sha256, storage_location, schema_definition, total_rows, total_columns,
                created_by, captured_at
            ) VALUES (%s, %s, %s, 1, 'LOCAL_FILE', '{}'::jsonb, repeat('a', 64), 's3://bucket/path',
                      '{}'::jsonb, 100, 2, %s, now());
            """,
            (ws.snapshot_id, tenant_id, ws.asset_id, owner),
        )
        cur.execute(
            """
            INSERT INTO rulesets (ruleset_id, tenant_id, asset_id, version, config_hash, status,
                created_by, submitted_by, submitted_at, approved_by, approved_at)
            VALUES (%s, %s, %s, '1.0.0', repeat('r', 64), 'ACTIVE', %s, %s, now(), %s, now());
            """,
            (ws.ruleset_id, tenant_id, ws.asset_id, owner, owner, owner),
        )
        cur.execute(
            """
            INSERT INTO scoring_policies (policy_id, tenant_id, version, config_hash, status,
                dimension_weights, gate_rules, created_by, submitted_by, submitted_at, approved_by, approved_at)
            VALUES (%s, %s, '1.0.0', repeat('p', 64), 'ACTIVE', '{}'::jsonb, '{}'::jsonb, %s, %s, now(), %s, now());
            """,
            (ws.policy_id, tenant_id, owner, owner, owner),
        )
    db_conn.commit()
    return ws


def seed_run(db_conn, ws: Workspace, owner: str, *, status: str = "QUEUED", age_minutes: int = 0) -> UUID:
    run_id = uuid4()
    created = datetime.now(UTC) - timedelta(minutes=age_minutes)
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluation_runs (
                run_id, tenant_id, snapshot_id, ruleset_id, policy_id, workload_tier, trigger_type,
                execution_profile, outlier_config, outlier_config_hash, priority, run_status,
                attempt_count, lease_generation, idempotency_key, created_by, created_at
            ) VALUES (%s, %s, %s, %s, %s, 'SMALL', 'ON_DEMAND', 'SPARK_K3S', '{}'::jsonb,
                      repeat('0', 64), 5, %s, 0, 0, %s, %s, %s);
            """,
            (run_id, ws.tenant_id, ws.snapshot_id, ws.ruleset_id, ws.policy_id, status,
             f"idem-{run_id}", ws.users[owner], created),
        )
    db_conn.commit()
    return run_id


def seed_event(db_conn, ws: Workspace, run_id: UUID, event_type: str, created_at: datetime, *,
               payload: dict | None = None, attempt: int = 1, event_id: UUID | None = None) -> UUID:
    event_id = event_id or uuid4()
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO run_events (event_id, tenant_id, run_id, event_type, attempt_count, lease_generation, "
            "event_payload, created_at) VALUES (%s, %s, %s, %s, %s, 1, %s, %s);",
            (event_id, ws.tenant_id, run_id, event_type, attempt, Jsonb(payload or {}), created_at),
        )
    db_conn.commit()
    return event_id


def login(client, ws: Workspace, name: str) -> dict[str, str]:
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": ws.emails[name], "password": PASSWORD, "tenant_id": str(ws.tenant_id)},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
