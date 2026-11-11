"""Authentication, tenant isolation, and inventory API tests."""

from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.core.config import Settings
from app.db.base import Base
from app.db.models import QRTag
from app.main import create_app


class FakeRedis:
    """Deterministic Redis health-check fake."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def setex(self, key: str, seconds: int, value: str) -> None:
        self.values[key] = value

    def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            deleted += self.values.pop(key, None) is not None
        return deleted

    def close(self) -> None:
        return None


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Run the app against an isolated SQLite database and fake Redis."""
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    redis_client = FakeRedis()
    monkeypatch.setattr(main_module, "create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(main_module.Redis, "from_url", lambda *args, **kwargs: redis_client)
    app = create_app(Settings(environment="test"))
    with TestClient(app) as test_client:
        yield test_client
    engine.dispose()


def register(client: TestClient, email: str, household_name: str) -> dict[str, object]:
    """Register a user and return the safe API payload."""
    response = client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "household_name": household_name,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def login(client: TestClient, email: str) -> str:
    """Authenticate and return the OAuth2 bearer token."""
    response = client.post(
        "/v1/auth/token",
        data={"username": email, "password": "correct horse battery staple"},
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def bearer(token: str) -> dict[str, str]:
    """Build authorization headers for an access token."""
    return {"Authorization": f"Bearer {token}"}


def test_registration_login_and_token_protected_me(client: TestClient) -> None:
    """Registration stores a verifier and authentication returns safe account data."""
    registration = register(client, "Owner@example.com", "Primary home")
    assert "password_hash" not in registration["user"]
    assert registration["user"]["email"] == "owner@example.com"
    assert registration["household"]["role"] == "owner"

    token = login(client, "OWNER@example.com")
    me = client.get("/v1/me", headers=bearer(token))
    assert me.status_code == 200
    assert me.json()["email"] == "owner@example.com"
    assert me.json()["households"] == [
        {
            "id": registration["household"]["id"],
            "name": "Primary home",
            "role": "owner",
        }
    ]

    invalid_login = client.post(
        "/v1/auth/token",
        data={"username": "owner@example.com", "password": "wrong password"},
    )
    assert invalid_login.status_code == 401
    assert invalid_login.json()["error"]["code"] == "invalid_credentials"
    assert invalid_login.json()["error"]["request_id"]
    assert client.get("/v1/me").status_code == 401
    assert client.get("/v1/me", headers=bearer(f"{token}tampered")).status_code == 401


def test_duplicate_registration_and_password_validation(client: TestClient) -> None:
    """Email uniqueness and minimum password length are enforced."""
    register(client, "member@example.com", "Member home")
    duplicate = client.post(
        "/v1/auth/register",
        json={
            "email": "MEMBER@example.com",
            "password": "correct horse battery staple",
            "household_name": "Duplicate home",
        },
    )
    assert duplicate.status_code == 409

    invalid = client.post(
        "/v1/auth/register",
        json={
            "email": "not-an-email",
            "password": "short",
            "household_name": "Invalid",
        },
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_request"
    assert invalid.json()["error"]["request_id"]


def test_tenant_scoped_inventory_crud_and_member_sharing(client: TestClient) -> None:
    """Households can manage inventory and cannot access another tenant's resources."""
    owner = register(client, "owner@example.com", "Owner household")
    owner_token = login(client, "owner@example.com")
    owner_headers = bearer(owner_token)
    household_id = owner["household"]["id"]

    property_response = client.post(
        "/v1/properties",
        json={"household_id": household_id, "name": "City home", "city": "Example"},
        headers=owner_headers,
    )
    assert property_response.status_code == 201, property_response.text
    property_id = property_response.json()["id"]

    appliance_response = client.post(
        "/v1/appliances",
        json={
            "property_id": property_id,
            "name": "Water purifier",
            "make": "Acme",
            "serial_number": "private-serial",
            "purchase_date": "2024-01-15",
        },
        headers=owner_headers,
    )
    assert appliance_response.status_code == 201, appliance_response.text
    appliance_id = appliance_response.json()["id"]
    assert appliance_response.json()["serial_number"] == "private-serial"
    with client.app.state.session_factory() as session:
        tag = QRTag(
            appliance_id=UUID(appliance_id),
            tag_id="phase-three-test-tag",
            public_fields=["make", "model"],
        )
        session.add(tag)
        session.commit()
        assert tag.id is not None

    technician_response = client.post(
        "/v1/technicians",
        json={
            "household_id": household_id,
            "name": "Service Co",
            "phone": "+1-555-0100",
        },
        headers=owner_headers,
    )
    assert technician_response.status_code == 201, technician_response.text
    technician_id = technician_response.json()["id"]

    service_response = client.post(
        f"/v1/appliances/{appliance_id}/service-records",
        json={
            "serviced_at": "2025-03-01",
            "description": "Replaced filter",
            "technician_id": technician_id,
            "cost": "49.95",
        },
        headers=owner_headers,
    )
    assert service_response.status_code == 201, service_response.text
    assert (
        len(
            client.get(
                f"/v1/appliances/{appliance_id}/service-records",
                headers=owner_headers,
            ).json()
        )
        == 1
    )
    service_record_id = service_response.json()["id"]

    other_owner = register(client, "other@example.com", "Other household")
    other_token = login(client, "other@example.com")
    other_headers = bearer(other_token)
    other_property = client.post(
        "/v1/properties",
        json={
            "household_id": other_owner["household"]["id"],
            "name": "Private property",
        },
        headers=other_headers,
    )
    assert other_property.status_code == 201
    assert client.get(f"/v1/properties/{property_id}", headers=other_headers).status_code == 404
    assert client.get(f"/v1/appliances/{appliance_id}", headers=other_headers).status_code == 404
    assert (
        client.post(
            "/v1/appliances",
            json={"property_id": property_id, "name": "Cross-tenant attempt"},
            headers=other_headers,
        ).status_code
        == 404
    )

    add_member = client.post(
        f"/v1/households/{household_id}/members",
        json={"email": "other@example.com"},
        headers=owner_headers,
    )
    assert add_member.status_code == 201, add_member.text
    assert client.get(f"/v1/properties/{property_id}", headers=other_headers).status_code == 200
    assert (
        client.post(
            f"/v1/households/{household_id}/members",
            json={"email": "owner@example.com"},
            headers=other_headers,
        ).status_code
        == 404
    )
    member_property = client.post(
        "/v1/properties",
        json={"household_id": household_id, "name": "Member-managed property"},
        headers=other_headers,
    )
    assert member_property.status_code == 201
    assert (
        client.get(f"/v1/households/{household_id}/members", headers=other_headers).status_code
        == 404
    )

    removed = client.delete(
        f"/v1/households/{household_id}/members/{other_owner['user']['id']}",
        headers=owner_headers,
    )
    assert removed.status_code == 200
    assert client.get(f"/v1/properties/{property_id}", headers=other_headers).status_code == 404
    assert (
        client.get(
            f"/v1/properties/{member_property.json()['id']}",
            headers=other_headers,
        ).status_code
        == 404
    )

    updated_service_record = client.patch(
        f"/v1/service-records/{service_record_id}",
        json={"description": "Replaced carbon filter"},
        headers=owner_headers,
    )
    assert updated_service_record.status_code == 200
    assert updated_service_record.json()["description"] == "Replaced carbon filter"
    assert (
        client.delete(
            f"/v1/service-records/{service_record_id}",
            headers=owner_headers,
        ).status_code
        == 204
    )
    assert (
        client.get(
            f"/v1/appliances/{appliance_id}/service-records",
            headers=owner_headers,
        ).json()
        == []
    )

    updated = client.patch(
        f"/v1/appliances/{appliance_id}",
        json={"name": "Updated purifier"},
        headers=owner_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Updated purifier"
    assert client.delete(f"/v1/appliances/{appliance_id}", headers=owner_headers).status_code == 204
    assert client.get(f"/v1/appliances/{appliance_id}", headers=owner_headers).status_code == 404

    updated_property = client.patch(
        f"/v1/properties/{property_id}",
        json={"city": "Updated city"},
        headers=owner_headers,
    )
    assert updated_property.status_code == 200
    assert updated_property.json()["city"] == "Updated city"
    assert client.delete(f"/v1/properties/{property_id}", headers=owner_headers).status_code == 204
    assert client.get(f"/v1/properties/{property_id}", headers=owner_headers).status_code == 404

    updated_technician = client.patch(
        f"/v1/technicians/{technician_id}",
        json={"organization": "Updated Service Co"},
        headers=owner_headers,
    )
    assert updated_technician.status_code == 200
    assert updated_technician.json()["organization"] == "Updated Service Co"
    assert (
        client.delete(f"/v1/technicians/{technician_id}", headers=owner_headers).status_code == 204
    )
    assert (
        client.patch(
            f"/v1/technicians/{technician_id}",
            json={"name": "Inactive technician"},
            headers=owner_headers,
        ).status_code
        == 404
    )


def test_token_and_schema_configuration_guardrails() -> None:
    """Token signing configuration cannot use its development fallback in production."""
    with pytest.raises(ValueError, match="jwt_secret_key"):
        Settings(environment="production")


def test_public_qr_tag_allowlist_cache_invalidation_and_revocation(client: TestClient) -> None:
    """Public pages expose only approved fields and reflect updates/revocation."""
    registration = register(client, "qr-owner@example.com", "QR home")
    headers = bearer(login(client, "qr-owner@example.com"))
    household_id = registration["household"]["id"]
    property_response = client.post(
        "/v1/properties",
        json={"household_id": household_id, "name": "Private address", "city": "Example"},
        headers=headers,
    )
    property_id = property_response.json()["id"]
    appliance_response = client.post(
        "/v1/appliances",
        json={
            "property_id": property_id,
            "name": "Water purifier",
            "make": "Acme",
            "model": "Clear 2",
            "serial_number": "private-serial-qr",
            "warranty_expiry": "2030-01-01",
        },
        headers=headers,
    )
    assert appliance_response.status_code == 201
    appliance_id = appliance_response.json()["id"]

    technician_response = client.post(
        "/v1/technicians",
        json={
            "household_id": household_id,
            "name": "Repair Team",
            "phone": "+1-555-0101",
            "email": "repair@example.com",
            "organization": "Repair Co",
        },
        headers=headers,
    )
    technician_id = technician_response.json()["id"]
    public_service = client.post(
        f"/v1/appliances/{appliance_id}/service-records",
        json={
            "serviced_at": "2025-03-01",
            "description": "Replaced the public filter",
            "technician_id": technician_id,
            "cost": "49.95",
            "is_public": True,
        },
        headers=headers,
    )
    assert public_service.status_code == 201
    private_service = client.post(
        f"/v1/appliances/{appliance_id}/service-records",
        json={
            "serviced_at": "2025-04-01",
            "description": "Private repair notes",
            "cost": "999.00",
        },
        headers=headers,
    )
    assert private_service.status_code == 201

    created_tag = client.post(
        f"/v1/appliances/{appliance_id}/tags",
        json={"public_fields": ["name", "make", "model", "warranty_expiry", "service_history"]},
        headers=headers,
    )
    assert created_tag.status_code == 201, created_tag.text
    tag_id = created_tag.json()["tag_id"]
    assert len(tag_id) >= 40
    assert created_tag.json()["scan_path"] == f"/v1/scan/{tag_id}"

    scan_path = created_tag.json()["scan_path"]
    first_scan = client.get(scan_path)
    scan_duration = first_scan.elapsed.total_seconds()
    assert first_scan.status_code == 200
    assert first_scan.headers["content-type"].startswith("text/html")
    assert first_scan.headers["cache-control"] == "no-store"
    assert len(first_scan.content) < 50_000
    assert scan_duration < 1
    assert "Water purifier" in first_scan.text
    assert "Acme" in first_scan.text and "Clear 2" in first_scan.text
    assert "2030-01-01" in first_scan.text
    assert "Replaced the public filter" in first_scan.text
    assert "Private repair notes" not in first_scan.text
    assert "private-serial-qr" not in first_scan.text
    assert "999.00" not in first_scan.text
    assert "Repair Team" not in first_scan.text
    assert client.app.state.redis.values
    assert all(
        len(value.encode("utf-8")) < 50_000 for value in client.app.state.redis.values.values()
    )

    cache_key = f"hometag:qr:v1:{tag_id}"
    second_public_service = client.post(
        f"/v1/appliances/{appliance_id}/service-records",
        json={
            "serviced_at": "2025-05-01",
            "description": "Second public visit",
            "is_public": True,
        },
        headers=headers,
    )
    assert second_public_service.status_code == 201
    assert cache_key not in client.app.state.redis.values
    refreshed_scan = client.get(scan_path)
    assert "Second public visit" in refreshed_scan.text

    updated_tag = client.patch(
        f"/v1/tags/{tag_id}",
        json={
            "public_fields": [
                "name",
                "technician_contact",
                "service_history",
            ]
        },
        headers=headers,
    )
    assert updated_tag.status_code == 200
    second_scan = client.get(scan_path)
    assert second_scan.status_code == 200
    assert "Repair Team" in second_scan.text
    assert "+1-555-0101" in second_scan.text
    assert "Replaced the public filter" in second_scan.text
    assert "Acme" not in second_scan.text
    assert "private-serial-qr" not in second_scan.text

    updated_appliance = client.patch(
        f"/v1/appliances/{appliance_id}",
        json={"name": "Changed purifier"},
        headers=headers,
    )
    assert updated_appliance.status_code == 200
    refreshed_appliance_scan = client.get(scan_path)
    assert "Changed purifier" in refreshed_appliance_scan.text
    assert "Water purifier" not in refreshed_appliance_scan.text

    for day in range(1, 13):
        long_public_service = client.post(
            f"/v1/appliances/{appliance_id}/service-records",
            json={
                "serviced_at": f"2025-06-{day:02d}",
                "description": "<" * 4000,
                "is_public": True,
            },
            headers=headers,
        )
        assert long_public_service.status_code == 201
    bounded_scan = client.get(scan_path)
    assert len(bounded_scan.content) < 50_000
    assert bounded_scan.text.count("<li>") == 10
    assert bounded_scan.text.count("&lt;") == 4970
    assert "..." in bounded_scan.text

    invalid = client.get("/v1/scan/unknown-phase-four-tag")
    assert invalid.status_code == 404
    assert invalid.text == client.get("/v1/scan/another-unknown-tag").text

    rotated = client.post(
        f"/v1/appliances/{appliance_id}/tags",
        json={"public_fields": ["name"]},
        headers=headers,
    )
    assert rotated.status_code == 201
    assert client.get(scan_path).status_code == 404
    assert client.get(rotated.json()["scan_path"]).status_code == 200
    assert client.delete(f"/v1/tags/{rotated.json()['tag_id']}", headers=headers).status_code == 204
    assert client.get(rotated.json()["scan_path"]).status_code == 404
    assert client.get(rotated.json()["scan_path"]).text == invalid.text


def test_openapi_documents_identity_and_inventory_routes(client: TestClient) -> None:
    """OpenAPI includes documented Phase 3 routes and field metadata."""
    schema = client.get("/openapi.json").json()

    for path in (
        "/v1/auth/register",
        "/v1/auth/token",
        "/v1/me",
        "/v1/households/{household_id}/members",
        "/v1/properties",
        "/v1/appliances",
        "/v1/technicians",
        "/v1/appliances/{appliance_id}/service-records",
        "/v1/scan/{tag_id}",
        "/v1/appliances/{appliance_id}/tags",
        "/v1/tags/{tag_id}",
    ):
        assert path in schema["paths"]

    register_schema = schema["components"]["schemas"]["RegisterRequest"]
    assert register_schema["properties"]["password"]["minLength"] == 12
    assert register_schema["properties"]["password"]["description"] == "Account password."
