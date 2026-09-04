from fastapi.testclient import TestClient

from apps.api.app.main import app


def test_error_envelope_and_role_matrix() -> None:
    client = TestClient(app)
    missing_auth = client.get("/api/v1/me")
    assert missing_auth.status_code == 401
    assert set(missing_auth.json()["error"]) == {
        "code",
        "message",
        "request_id",
        "retryable",
        "details",
    }
    forbidden = client.get("/api/v1/admin/audit", headers={"X-Debug-Role": "ANALYST"})
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "ROLE_REQUIRED"
    unknown = client.get("/api/v1/does-not-exist")
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


def test_admin_credentials_issue_an_admin_session() -> None:
    invalid_client = TestClient(app)
    invalid = invalid_client.post(
        "/api/v1/auth/admin/login",
        json={"username": "dev", "password": "wrong"},
    )
    assert invalid.status_code == 401
    assert invalid.json()["error"]["code"] == "ADMIN_CREDENTIALS_INVALID"
    assert invalid.cookies.get("session") is None

    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/admin/login",
        json={"username": "dev", "password": "1234"},
    )
    assert response.status_code == 204
    assert response.cookies.get("session")
    assert response.cookies.get("csrf")

    current_user = client.get("/api/v1/me")
    assert current_user.status_code == 200
    assert current_user.json()["role"] == "ADMIN"


def test_admin_concurrency_headers_are_required() -> None:
    client = TestClient(app)
    source_id = next(iter(__import__("apps.api.app.state", fromlist=["STATE"]).STATE.sources))
    response = client.patch(
        f"/api/v1/admin/sources/{source_id}",
        json={"values": {"active": False}, "reason": "test"},
        headers={"X-Debug-Role": "ADMIN", "X-CSRF-Token": "local-csrf"},
    )
    assert response.status_code == 422 or response.status_code == 400


def test_openapi_has_unique_operation_ids_and_stable_errors() -> None:
    schema = app.openapi()
    methods = {"get", "post", "put", "patch", "delete"}
    operations = [item[method] for item in schema["paths"].values() for method in item if method in methods]
    ids = [operation["operationId"] for operation in operations]
    assert len(ids) == len(set(ids))
    assert all("400" in operation["responses"] and "422" in operation["responses"] for operation in operations)
