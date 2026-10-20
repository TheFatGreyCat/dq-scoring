"""My-jobs ownership scoping: server derives the owner from the token, never from the client."""

from __future__ import annotations

from uuid import uuid4

import pytest

from tests.support.job_seed import login, seed_run, seed_workspace


@pytest.fixture
def world(db_conn, client):
    ws = seed_workspace(db_conn, {"alice": "DATA_ENGINEER", "bob": "DATA_ENGINEER", "admin": "WORKSPACE_ADMIN"})
    other = seed_workspace(db_conn, {"carol": "DATA_ENGINEER", "boss": "WORKSPACE_ADMIN"})
    runs = {
        "alice": [seed_run(db_conn, ws, "alice", age_minutes=i) for i in range(3)],
        "bob": [seed_run(db_conn, ws, "bob", status="RUNNING", age_minutes=10 + i) for i in range(2)],
        "carol": [seed_run(db_conn, other, "carol")],
    }
    return {
        "ws": ws,
        "runs": runs,
        "alice": login(client, ws, "alice"),
        "bob": login(client, ws, "bob"),
        "admin": login(client, ws, "admin"),
        "carol": login(client, other, "carol"),
    }


def ids(response):
    assert response.status_code == 200, response.text
    return {row["run_id"] for row in response.json()["items"]}


def test_mine_excludes_same_tenant_other_owner_and_other_tenant(client, world):
    got = ids(client.get("/api/v1/runs", params={"scope": "mine"}, headers=world["alice"]))
    assert got == {str(r) for r in world["runs"]["alice"]}
    got_bob = ids(client.get("/api/v1/runs", params={"scope": "mine"}, headers=world["bob"]))
    assert got_bob == {str(r) for r in world["runs"]["bob"]}


def test_mine_total_and_paging_are_owner_scoped(client, world):
    first = client.get("/api/v1/runs", params={"scope": "mine", "page_size": 2}, headers=world["alice"]).json()
    second = client.get("/api/v1/runs", params={"scope": "mine", "page_size": 2, "page": 2}, headers=world["alice"]).json()
    assert first["total"] == second["total"] == 3
    assert len(first["items"]) == 2 and len(second["items"]) == 1
    assert {r["run_id"] for r in first["items"]}.isdisjoint(r["run_id"] for r in second["items"])


def test_mine_marks_ownership_and_never_trusts_client_identity(client, world):
    rows = client.get("/api/v1/runs", params={"scope": "mine"}, headers=world["alice"]).json()["items"]
    assert all(r["owned_by_me"] is True for r in rows)
    forged = client.get(
        "/api/v1/runs",
        params={"scope": "mine", "created_by": str(world["ws"].users["bob"])},
        headers=world["alice"],
    )
    assert forged.status_code in (403, 422)
    assert str(world["runs"]["bob"][0]) not in {r["run_id"] for r in forged.json().get("items", [])}


def test_scope_value_is_validated(client, world):
    assert client.get("/api/v1/runs", params={"scope": "everyone"}, headers=world["alice"]).status_code == 422


def test_non_admin_cannot_use_creator_filter(client, world):
    response = client.get(
        "/api/v1/runs",
        params={"scope": "workspace", "created_by": str(world["ws"].users["bob"])},
        headers=world["alice"],
    )
    assert response.status_code == 403


def test_admin_workspace_list_is_tenant_wide_and_creator_filterable(client, world):
    everyone = ids(client.get("/api/v1/runs", params={"scope": "workspace"}, headers=world["admin"]))
    assert everyone == {str(r) for r in world["runs"]["alice"] + world["runs"]["bob"]}
    assert str(world["runs"]["carol"][0]) not in everyone
    only_bob = client.get(
        "/api/v1/runs",
        params={"scope": "workspace", "created_by": str(world["ws"].users["bob"])},
        headers=world["admin"],
    )
    assert ids(only_bob) == {str(r) for r in world["runs"]["bob"]}
    assert {r["created_by"] for r in only_bob.json()["items"]} == {str(world["ws"].users["bob"])}


def test_admin_scope_mine_is_still_own_jobs_only(client, world):
    assert ids(client.get("/api/v1/runs", params={"scope": "mine"}, headers=world["admin"])) == set()


def test_default_scope_is_mine_for_non_admin_and_workspace_for_admin(client, world):
    assert ids(client.get("/api/v1/runs", headers=world["alice"])) == {str(r) for r in world["runs"]["alice"]}
    assert ids(client.get("/api/v1/runs", headers=world["admin"])) == {str(r) for r in world["runs"]["alice"] + world["runs"]["bob"]}


def test_non_admin_cannot_request_workspace_scope(client, world):
    assert client.get("/api/v1/runs", params={"scope": "workspace"}, headers=world["alice"]).status_code == 403


def test_creator_identity_only_exposed_in_admin_workspace_view(client, world):
    mine = client.get("/api/v1/runs", headers=world["alice"]).json()["items"]
    assert all(r["created_by"] is None for r in mine)
    admin_rows = client.get("/api/v1/runs", headers=world["admin"]).json()["items"]
    assert all(r["created_by"] for r in admin_rows)
    assert {r["owned_by_me"] for r in admin_rows} == {False}


def test_creator_filter_other_tenant_user_yields_nothing(client, world, db_conn):
    carol = str(next(iter(seed_workspace(db_conn, {"x": "DATA_ENGINEER"}).users.values())))
    response = client.get("/api/v1/runs", params={"scope": "workspace", "created_by": carol}, headers=world["admin"])
    assert ids(response) == set()


def test_status_enforces_ownership_for_non_admin_with_or_without_scope(client, world):
    alice_run, bob_run, carol_run = world["runs"]["alice"][0], world["runs"]["bob"][0], world["runs"]["carol"][0]
    for params in ({}, {"scope": "mine"}):
        assert client.get(f"/api/v1/runs/{alice_run}/status", params=params, headers=world["alice"]).status_code == 200
        assert client.get(f"/api/v1/runs/{bob_run}/status", params=params, headers=world["alice"]).status_code == 404
        assert client.get(f"/api/v1/runs/{carol_run}/status", params=params, headers=world["alice"]).status_code == 404
    assert client.get(f"/api/v1/runs/{bob_run}/status", params={"scope": "workspace"}, headers=world["alice"]).status_code == 403


def test_admin_status_workspace_default_and_mine_restriction(client, world):
    bob_run = world["runs"]["bob"][0]
    view = client.get(f"/api/v1/runs/{bob_run}/status", headers=world["admin"])
    assert view.status_code == 200
    assert view.json()["created_by"] == str(world["ws"].users["bob"]) and view.json()["owned_by_me"] is False
    assert client.get(f"/api/v1/runs/{bob_run}/status", params={"scope": "mine"}, headers=world["admin"]).status_code == 404
    assert client.get(f"/api/v1/runs/{world['runs']['carol'][0]}/status", headers=world["admin"]).status_code == 404


def test_owner_status_reports_ownership_without_leaking_identity(client, world):
    own = client.get(f"/api/v1/runs/{world['runs']['alice'][0]}/status", headers=world["alice"]).json()
    assert own["owned_by_me"] is True and own["created_by"] is None


def test_unknown_run_is_404(client, world):
    assert client.get(f"/api/v1/runs/{uuid4()}/status", params={"scope": "mine"}, headers=world["alice"]).status_code == 404
