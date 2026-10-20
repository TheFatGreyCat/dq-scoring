from uuid import uuid4

from dq_scoring.presentation.api.auth import AuthenticatedUser, create_access_token
from dq_scoring.presentation.api.config import get_api_settings


def headers(role):
    user = AuthenticatedUser(
        user_id=uuid4(), tenant_id=uuid4(), email="synthetic@example.test", role=role
    )
    token = create_access_token(user, get_api_settings().jwt_secret)
    return user, {"Authorization": f"Bearer {token}"}


def test_monitor_gate_and_identity_do_not_require_database(client):
    user, viewer = headers("VIEWER")
    assert client.get("/api/v1/operations/monitor").status_code == 401
    assert client.get("/api/v1/operations/monitor", headers=viewer).status_code == 403
    assert client.get("/api/v1/operations/config", headers=viewer).status_code == 403
    response = client.get("/api/v1/auth/me", headers=viewer)
    assert response.status_code == 200
    assert response.json() == user.model_dump(mode="json")


def test_admin_monitor_returns_real_components(client):
    _, admin = headers("WORKSPACE_ADMIN")
    response = client.get("/api/v1/operations/monitor", headers=admin)
    assert response.status_code == 200, response.text
    assert response.json()["components"]["database"] == "up"
    assert response.json()["queue"]["queued"] == 0


# --- adapter observations (provenance, OFF vs unknown vs down) ---------------------------------

import pytest
from psycopg.types.json import Jsonb

from dq_scoring.adapters.llm.gateway_settings import LlmSettings, get_llm_settings


@pytest.fixture
def admin_client(client):
    _, admin = headers("WORKSPACE_ADMIN")
    yield client, admin
    client.app.dependency_overrides.pop(get_llm_settings, None)


@pytest.fixture
def worker_row(db_conn):
    def put(age_seconds, metrics):
        db_conn.execute("DELETE FROM worker_monitor_snapshots WHERE worker_id='synthetic-eval';")
        db_conn.execute(
            "INSERT INTO worker_monitor_snapshots (worker_id,kind,started_at,heartbeat_at,ready,busy,last_error_code,metrics) "
            "VALUES ('synthetic-eval','EVALUATION',now(),now()-make_interval(secs=>%s),true,false,NULL,%s);",
            (age_seconds, Jsonb(metrics)),
        )
        db_conn.commit()
    yield put
    db_conn.execute("DELETE FROM worker_monitor_snapshots WHERE worker_id='synthetic-eval';")
    db_conn.commit()


def adapters(client, admin):
    response = client.get("/api/v1/operations/monitor", headers=admin)
    assert response.status_code == 200, response.text
    return {a["name"]: a for a in response.json()["adapters"]}


def test_gateway_off_is_off_not_down_and_nothing_is_probed(admin_client):
    client, admin = admin_client
    client.app.dependency_overrides[get_llm_settings] = lambda: LlmSettings(enabled=False)
    gateway = adapters(client, admin)["advisory_gateway"]
    assert gateway["state"] == "off"
    assert gateway["source"] == "configuration"


def test_gateway_enabled_without_credentials_is_not_configured(admin_client):
    client, admin = admin_client
    client.app.dependency_overrides[get_llm_settings] = lambda: LlmSettings(enabled=True)
    assert adapters(client, admin)["advisory_gateway"]["state"] == "not_configured"


def test_configured_gateway_is_unknown_never_up_and_leaks_no_destination(admin_client):
    client, admin = admin_client
    client.app.dependency_overrides[get_llm_settings] = lambda: LlmSettings(
        enabled=True, endpoint="https://gateway.synthetic.test/v1/chat", model="m", api_key="synthetic-key-value"
    )
    response = client.get("/api/v1/operations/monitor", headers=admin)
    gateway = {a["name"]: a for a in response.json()["adapters"]}["advisory_gateway"]
    assert gateway["state"] == "unknown" and gateway["checked_at"] is None
    assert "gateway.synthetic.test" not in response.text and "synthetic-key-value" not in response.text


def test_database_and_storage_report_probe_source_and_time(admin_client):
    client, admin = admin_client
    found = adapters(client, admin)
    assert found["database"]["state"] == "up" and found["database"]["source"] == "probe"
    assert found["database"]["checked_at"] is not None and found["database"]["last_success_at"] is not None
    assert found["storage"]["state"] in {"up", "degraded", "down"} and found["storage"]["source"] == "probe"


def test_spark_without_worker_is_unknown_not_up_or_down(admin_client):
    client, admin = admin_client
    spark = adapters(client, admin)["spark_compute"]
    assert spark["state"] == "unknown" and spark["checked_at"] is None and spark["last_success_at"] is None


def test_spark_from_fresh_heartbeat_is_up_with_worker_source(admin_client, worker_row):
    client, admin = admin_client
    worker_row(1, {"spark_status": "up", "master_status": "unknown", "mode": "KUBERNETES"})
    spark = adapters(client, admin)["spark_compute"]
    assert spark["state"] == "up" and spark["source"] == "worker_heartbeat"
    assert spark["stale"] is False and spark["checked_at"] is not None


def test_spark_from_old_heartbeat_is_stale_unknown_with_last_success(admin_client, worker_row):
    client, admin = admin_client
    worker_row(300, {"spark_status": "up", "master_status": "up"})
    spark = adapters(client, admin)["spark_compute"]
    assert spark["state"] == "unknown" and spark["stale"] is True
    assert spark["last_success_at"] is not None


def test_cluster_spark_counts_are_labelled_cluster_scope(admin_client):
    client, admin = admin_client
    assert client.get("/api/v1/operations/monitor", headers=admin).json()["spark"]["scope"] == "CLUSTER"
