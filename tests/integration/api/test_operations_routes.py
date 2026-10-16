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
