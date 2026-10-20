"""Run execution projection: request state vs per-run Spark observation, attempt/lease bound, safe by role."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from psycopg.types.json import Jsonb

from tests.support.job_seed import login, seed_run, seed_workspace

APP_ID = "app-20261001120000-0042"


def spark_payload(group: str, *, job_id: int = 7, active: int = 2, application_id: str = APP_ID) -> dict:
    return {
        "application_id": application_id,
        "group_id": group,
        "jobs": [{
            "job_id": job_id, "status": "RUNNING", "stages": 3, "tasks": 40,
            "active_tasks": active, "completed_tasks": 30, "failed_tasks": 0,
        }],
    }


def put_event(db_conn, ws, run_id: UUID, event_type: str, generation: int, created_at: datetime, payload: dict | None = None) -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO run_events (event_id, tenant_id, run_id, event_type, attempt_count, lease_generation, "
            "event_payload, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);",
            (uuid4(), ws.tenant_id, run_id, event_type, generation, generation, Jsonb(payload or {}), created_at),
        )
    db_conn.commit()


def set_state(db_conn, run_id: UUID, status: str, generation: int) -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            "UPDATE evaluation_runs SET run_status=%s, lease_generation=%s, attempt_count=%s, "
            "started_at=now(), heartbeat_at=now() WHERE run_id=%s;",
            (status, generation, generation, run_id),
        )
    db_conn.commit()


@pytest.fixture
def world(db_conn, client):
    ws = seed_workspace(db_conn, {"alice": "DATA_ENGINEER", "bob": "DATA_ENGINEER", "admin": "WORKSPACE_ADMIN"})
    other = seed_workspace(db_conn, {"carol": "DATA_ENGINEER"})
    now = datetime.now(UTC)
    run_a = seed_run(db_conn, ws, "alice")
    run_b = seed_run(db_conn, ws, "bob")
    foreign = seed_run(db_conn, other, "carol")
    set_state(db_conn, run_a, "RUNNING", 1)
    set_state(db_conn, run_b, "RUNNING", 1)
    set_state(db_conn, foreign, "RUNNING", 1)
    put_event(db_conn, ws, run_a, "RUN_CLAIMED", 1, now - timedelta(seconds=30))
    put_event(db_conn, ws, run_a, "SPARK_OBSERVED", 1, now - timedelta(seconds=2), spark_payload(f"dq-run-{run_a}-g1", job_id=11))
    put_event(db_conn, ws, run_b, "RUN_CLAIMED", 1, now - timedelta(seconds=30))
    put_event(db_conn, ws, run_b, "SPARK_OBSERVED", 1, now - timedelta(seconds=2), spark_payload(f"dq-run-{run_b}-g1", job_id=99, active=5))
    put_event(db_conn, other, foreign, "RUN_CLAIMED", 1, now - timedelta(seconds=30))
    return {
        "ws": ws, "other": other, "a": run_a, "b": run_b, "foreign": foreign, "now": now,
        "alice": login(client, ws, "alice"), "bob": login(client, ws, "bob"),
        "admin": login(client, ws, "admin"), "carol": login(client, other, "carol"),
    }


def execution(client, run_id, headers, **params):
    return client.get(f"/api/v1/runs/{run_id}/execution", params=params, headers=headers)


def test_owner_sees_request_and_spark_observation_separately(client, world):
    response = execution(client, world["a"], world["alice"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["request"]["status"] == "RUNNING"
    [attempt] = body["attempts"]
    assert attempt["lease_generation"] == 1
    assert attempt["spark"]["state"] == "OBSERVED"
    assert [job["job_id"] for job in attempt["spark"]["jobs"]] == [11]


def test_runs_are_isolated_from_each_other(client, world):
    jobs_a = execution(client, world["a"], world["alice"]).json()["attempts"][0]["spark"]["jobs"]
    jobs_b = execution(client, world["b"], world["bob"]).json()["attempts"][0]["spark"]["jobs"]
    assert [j["job_id"] for j in jobs_a] == [11]
    assert [j["job_id"] for j in jobs_b] == [99]
    assert jobs_b[0]["active_tasks"] == 5


def test_cluster_identifiers_are_admin_only(client, world):
    owner = execution(client, world["a"], world["alice"]).json()["attempts"][0]["spark"]
    assert owner["application_id"] is None and owner["group_id"] is None
    assert APP_ID not in str(execution(client, world["a"], world["alice"]).json())
    admin = execution(client, world["a"], world["admin"]).json()["attempts"][0]["spark"]
    assert admin["application_id"] == APP_ID
    assert admin["group_id"] == f"dq-run-{world['a']}-g1"


def test_authorization_matches_run_events(client, world):
    assert execution(client, world["a"], world["bob"]).status_code == 404
    assert execution(client, world["a"], world["carol"]).status_code == 404
    assert execution(client, world["foreign"], world["alice"]).status_code == 404
    assert execution(client, uuid4(), world["alice"]).status_code == 404
    assert execution(client, world["a"], world["bob"], scope="workspace").status_code == 403
    assert execution(client, world["a"], world["alice"], scope="bogus").status_code == 422
    assert execution(client, world["a"], world["admin"], scope="mine").status_code == 404
    assert execution(client, world["a"], world["admin"]).status_code == 200


def test_old_observation_is_stale_not_fresh(client, world, db_conn):
    run = seed_run(db_conn, world["ws"], "alice")
    set_state(db_conn, run, "RUNNING", 1)
    put_event(db_conn, world["ws"], run, "RUN_CLAIMED", 1, world["now"] - timedelta(minutes=5))
    put_event(db_conn, world["ws"], run, "SPARK_OBSERVED", 1, world["now"] - timedelta(minutes=3), spark_payload("g"))
    spark = execution(client, run, world["alice"]).json()["attempts"][0]["spark"]
    assert spark["state"] == "STALE"
    assert spark["observed_at"] is not None


def test_no_observation_is_unknown_never_idle_or_zero(client, world, db_conn):
    run = seed_run(db_conn, world["ws"], "alice")
    set_state(db_conn, run, "RUNNING", 1)
    put_event(db_conn, world["ws"], run, "RUN_CLAIMED", 1, world["now"])
    spark = execution(client, run, world["alice"]).json()["attempts"][0]["spark"]
    assert spark == {"state": "UNKNOWN", "observed_at": None, "application_id": None, "group_id": None, "jobs": []}


def test_retry_binds_observation_to_its_own_generation(client, world, db_conn):
    run = seed_run(db_conn, world["ws"], "alice")
    set_state(db_conn, run, "RUNNING", 2)
    ws, now = world["ws"], world["now"]
    put_event(db_conn, ws, run, "RUN_CLAIMED", 1, now - timedelta(minutes=2))
    put_event(db_conn, ws, run, "SPARK_OBSERVED", 1, now - timedelta(seconds=1), spark_payload("old", job_id=1))
    put_event(db_conn, ws, run, "RUN_CLAIMED", 2, now - timedelta(seconds=5))
    attempts = execution(client, run, world["alice"]).json()["attempts"]
    by_generation = {a["lease_generation"]: a for a in attempts}
    assert by_generation[2]["spark"]["state"] == "UNKNOWN" and by_generation[2]["spark"]["jobs"] == []
    assert by_generation[1]["spark"]["state"] == "ENDED"
    assert by_generation[1]["spark"]["jobs"][0]["job_id"] == 1


def test_terminal_run_ends_observation(client, world, db_conn):
    run = seed_run(db_conn, world["ws"], "alice")
    set_state(db_conn, run, "SUCCEEDED", 1)
    ws, now = world["ws"], world["now"]
    put_event(db_conn, ws, run, "RUN_CLAIMED", 1, now - timedelta(seconds=9))
    put_event(db_conn, ws, run, "SPARK_OBSERVED", 1, now - timedelta(seconds=1), spark_payload("g"))
    put_event(db_conn, ws, run, "RUN_SUCCEEDED", 1, now)
    body = execution(client, run, world["alice"]).json()
    assert body["attempts"][0]["spark"]["state"] == "ENDED"
    assert body["attempts"][0]["outcome"] == "RUN_SUCCEEDED"


def test_malformed_payload_degrades_to_unknown_without_leaking(client, world, db_conn):
    run = seed_run(db_conn, world["ws"], "alice")
    set_state(db_conn, run, "RUNNING", 1)
    ws, now = world["ws"], world["now"]
    put_event(db_conn, ws, run, "RUN_CLAIMED", 1, now)
    put_event(db_conn, ws, run, "SPARK_OBSERVED", 1, now, {"application_id": "x", "jobs": "s3://secret-bucket/key password=hunter2"})
    response = execution(client, run, world["admin"])
    assert response.status_code == 200
    assert response.json()["attempts"][0]["spark"]["state"] == "UNKNOWN"
    assert "hunter2" not in response.text and "secret-bucket" not in response.text


def test_attempts_and_jobs_are_bounded(client, world, db_conn):
    run = seed_run(db_conn, world["ws"], "alice")
    set_state(db_conn, run, "RUNNING", 15)
    ws, now = world["ws"], world["now"]
    for generation in range(1, 16):
        put_event(db_conn, ws, run, "RUN_CLAIMED", generation, now - timedelta(minutes=20 - generation))
    jobs = [{"job_id": i, "status": "RUNNING", "stages": 1, "tasks": 1, "active_tasks": 0, "completed_tasks": 0, "failed_tasks": 0} for i in range(60)]
    put_event(db_conn, ws, run, "SPARK_OBSERVED", 15, now, {"application_id": APP_ID, "group_id": "g", "jobs": jobs})
    body = execution(client, run, world["alice"]).json()
    assert len(body["attempts"]) <= 10
    assert body["attempts"][0]["lease_generation"] == 15
    assert len(body["attempts"][0]["spark"]["jobs"]) <= 20
