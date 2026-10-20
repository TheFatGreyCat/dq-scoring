"""Run event timeline: parent authorization first, bounded allowlisted projection, stable cursor paging."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from tests.support.job_seed import login, seed_event, seed_run, seed_workspace

T0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def world(db_conn, client):
    ws = seed_workspace(db_conn, {"alice": "DATA_ENGINEER", "bob": "DATA_ENGINEER", "admin": "WORKSPACE_ADMIN"})
    other = seed_workspace(db_conn, {"carol": "DATA_ENGINEER"})
    alice_run = seed_run(db_conn, ws, "alice", status="FAILED")
    carol_run = seed_run(db_conn, other, "carol")
    seed_event(db_conn, ws, alice_run, "RUN_QUEUED", T0, attempt=0)
    seed_event(db_conn, ws, alice_run, "RUN_CLAIMED", T0 + timedelta(seconds=1))
    seed_event(
        db_conn, ws, alice_run, "RUN_FAILED", T0 + timedelta(seconds=2),
        payload={"error": "STORAGE_UNAVAILABLE: s3://secret-bucket/key?X-Amz-Signature=abc host=10.0.0.5 password=hunter2"},
    )
    seed_event(db_conn, other, carol_run, "RUN_QUEUED", T0, attempt=0)
    return {
        "ws": ws, "alice_run": alice_run, "carol_run": carol_run,
        "alice": login(client, ws, "alice"), "bob": login(client, ws, "bob"),
        "admin": login(client, ws, "admin"), "carol": login(client, other, "carol"),
    }


def events(client, run_id, headers, **params):
    return client.get(f"/api/v1/runs/{run_id}/events", params=params, headers=headers)


def test_owner_sees_ordered_timeline(client, world):
    response = events(client, world["alice_run"], world["alice"])
    assert response.status_code == 200
    body = response.json()
    assert [e["event_type"] for e in body["items"]] == ["RUN_QUEUED", "RUN_CLAIMED", "RUN_FAILED"]
    assert body["next_cursor"] is None


def test_payload_is_never_projected_and_error_is_allowlisted(client, world):
    body = events(client, world["alice_run"], world["alice"]).json()
    raw = str(body)
    for leaked in ("secret-bucket", "X-Amz-Signature", "10.0.0.5", "hunter2", "event_payload"):
        assert leaked not in raw
    failed = body["items"][-1]
    assert failed["error_code"] == "STORAGE_UNAVAILABLE"
    assert set(failed) == {"event_id", "event_type", "attempt_count", "lease_generation", "created_at", "error_code"}


def test_unknown_event_type_and_error_collapse_to_generic_codes(client, world, db_conn):
    seed_event(db_conn, world["ws"], world["alice_run"], "SOMETHING_INTERNAL", T0 + timedelta(seconds=3),
               payload={"error": "Traceback (most recent call last): boom"})
    seed_event(db_conn, world["ws"], world["alice_run"], "RUN_FAILED", T0 + timedelta(seconds=4),
               payload={"error": "Traceback (most recent call last): boom"})
    items = events(client, world["alice_run"], world["alice"]).json()["items"]
    assert items[3]["event_type"] == "RUN_EVENT"
    assert items[3]["error_code"] is None
    assert items[4]["error_code"] == "RUN_EXECUTION_FAILED"


def test_other_owner_same_tenant_cannot_read_events(client, world):
    assert events(client, world["alice_run"], world["bob"]).status_code == 404
    assert events(client, world["alice_run"], world["bob"], scope="mine").status_code == 404


def test_other_tenant_and_unknown_run_are_404(client, world):
    assert events(client, world["carol_run"], world["alice"]).status_code == 404
    assert events(client, world["alice_run"], world["carol"]).status_code == 404
    assert events(client, uuid4(), world["alice"]).status_code == 404


def test_forged_workspace_scope_denied_for_non_admin(client, world):
    assert events(client, world["alice_run"], world["bob"], scope="workspace").status_code == 403
    assert events(client, world["alice_run"], world["alice"], scope="workspace").status_code == 403
    assert events(client, world["alice_run"], world["bob"], scope="bogus").status_code == 422


def test_admin_defaults_to_workspace_events(client, world):
    assert events(client, world["alice_run"], world["admin"]).status_code == 200


def test_admin_can_read_workspace_events_but_not_mine_of_others(client, world):
    assert events(client, world["alice_run"], world["admin"], scope="workspace").status_code == 200
    assert events(client, world["alice_run"], world["admin"], scope="mine").status_code == 404
    assert events(client, world["carol_run"], world["admin"], scope="workspace").status_code == 404


def test_cursor_paging_is_stable_with_ties_and_late_events(client, world, db_conn):
    run = seed_run(db_conn, world["ws"], "alice")
    ids = sorted((uuid4() for _ in range(5)), key=str)
    for event_id in ids:  # identical timestamps: event_id must break the tie
        seed_event(db_conn, world["ws"], run, "RUN_QUEUED", T0, event_id=event_id)
    first = events(client, run, world["alice"], limit=2).json()
    assert [UUID(e["event_id"]) for e in first["items"]] == ids[:2]
    assert first["next_cursor"]
    late = seed_event(db_conn, world["ws"], run, "RUN_CLAIMED", T0 + timedelta(seconds=9))
    second = events(client, run, world["alice"], limit=2, cursor=first["next_cursor"]).json()
    third = events(client, run, world["alice"], limit=10, cursor=second["next_cursor"]).json()
    seen = [UUID(e["event_id"]) for e in first["items"] + second["items"] + third["items"]]
    assert seen == [*ids, late]
    assert third["next_cursor"] is None


def test_limit_is_bounded_and_cursor_is_validated(client, world):
    assert events(client, world["alice_run"], world["alice"], limit=0).status_code == 422
    assert events(client, world["alice_run"], world["alice"], limit=101).status_code == 422
    assert events(client, world["alice_run"], world["alice"], cursor="not-a-cursor").status_code == 422


def test_cursor_cannot_cross_runs(client, world, db_conn):
    run_a = seed_run(db_conn, world["ws"], "alice")
    run_b = seed_run(db_conn, world["ws"], "alice")
    for n in range(3):
        seed_event(db_conn, world["ws"], run_a, "RUN_QUEUED", T0 + timedelta(hours=1, seconds=n))
        seed_event(db_conn, world["ws"], run_b, "RUN_QUEUED", T0 + timedelta(seconds=n))
    cursor_a = events(client, run_a, world["alice"], limit=2).json()["next_cursor"]
    assert cursor_a
    assert events(client, run_a, world["alice"], cursor=cursor_a).status_code == 200
    assert events(client, run_b, world["alice"], cursor=cursor_a).status_code == 422


def test_spark_observations_are_not_part_of_the_timeline(client, world, db_conn):
    run = seed_run(db_conn, world["ws"], "alice")
    seed_event(db_conn, world["ws"], run, "RUN_QUEUED", T0)
    seed_event(db_conn, world["ws"], run, "SPARK_OBSERVED", T0 + timedelta(seconds=1), payload={"application_id": "app-1"})
    body = events(client, run, world["alice"]).json()
    assert [e["event_type"] for e in body["items"]] == ["RUN_QUEUED"]
