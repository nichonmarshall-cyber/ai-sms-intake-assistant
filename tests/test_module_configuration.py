"""Tenant-scoped, versioned configuration for AI Memory and AI Scheduling."""

from modules import entitlements
from modules.db import session_scope
from modules.models import AuditEvent, BusinessModuleConfiguration
from tests.conftest import auth_headers, login, make_business, make_membership, make_platform_user


PASSWORD = "correct-horse-battery-staple"


def _owner(business, email="module-owner@test.local"):
    user = make_platform_user(email=email, password=PASSWORD, platform_role="none")
    make_membership(business.id, user.id, role="owner")
    return user


def _enable(business_id: str, module_key: str):
    db = session_scope()
    try:
        entitlements.set_module(db, business_id, module_key, True)
        db.commit()
    finally:
        db.close()


def test_memory_configuration_requires_entitlement(demo_app):
    business = make_business()
    _owner(business)
    client, _, _ = login(demo_app, "module-owner@test.local", PASSWORD)
    response = client.get(f"/api/dashboard/businesses/{business.id}/ai-memory/configuration")
    assert response.status_code == 403


def test_memory_defaults_and_validated_update_are_versioned_and_audited(demo_app):
    business = make_business()
    _owner(business)
    _enable(business.id, "ai_memory")
    client, csrf, _ = login(demo_app, "module-owner@test.local", PASSWORD)

    initial = client.get(
        f"/api/dashboard/businesses/{business.id}/ai-memory/configuration"
    )
    assert initial.status_code == 200
    assert initial.get_json()["version"] == 0
    assert initial.get_json()["configuration"]["retention_days"] == 365

    configuration = initial.get_json()["configuration"]
    configuration["record_types"] = [{
        "key": "asset",
        "label": "Customer asset",
        "fields": [{
            "key": "serial_number",
            "label": "Serial number",
            "type": "text",
            "ai_visibility": "read_only",
            "update_authority": "employee_only",
            "sensitivity": "standard",
        }],
    }]
    response = client.put(
        f"/api/dashboard/businesses/{business.id}/ai-memory/configuration",
        json={"configuration": configuration, "expected_version": 0},
        headers=auth_headers(csrf),
    )
    assert response.status_code == 200
    assert response.get_json()["version"] == 1

    db = session_scope()
    try:
        stored = db.query(BusinessModuleConfiguration).filter_by(
            business_id=business.id, module_key="ai_memory"
        ).one()
        assert stored.configuration["record_types"][0]["key"] == "asset"
        audit = db.query(AuditEvent).filter_by(
            business_id=business.id,
            action="business.module_configuration.update",
        ).one()
        assert audit.details["module"] == "ai_memory"
    finally:
        db.close()


def test_restricted_memory_field_must_be_hidden(demo_app):
    business = make_business()
    _owner(business)
    _enable(business.id, "ai_memory")
    client, csrf, _ = login(demo_app, "module-owner@test.local", PASSWORD)
    response = client.put(
        f"/api/dashboard/businesses/{business.id}/ai-memory/configuration",
        json={
            "expected_version": 0,
            "configuration": {
                "record_types": [{
                    "key": "account",
                    "label": "Account",
                    "fields": [{
                        "key": "secret",
                        "label": "Secret",
                        "type": "text",
                        "ai_visibility": "read_only",
                        "update_authority": "employee_only",
                        "sensitivity": "restricted",
                    }],
                }],
            },
        },
        headers=auth_headers(csrf),
    )
    assert response.status_code == 400
    assert "hidden" in response.get_json()["error"].lower()


def test_scheduling_configuration_rejects_stale_update(demo_app):
    business = make_business()
    _owner(business)
    _enable(business.id, "ai_scheduling")
    client, csrf, _ = login(demo_app, "module-owner@test.local", PASSWORD)
    url = f"/api/dashboard/businesses/{business.id}/ai-scheduling/configuration"
    configuration = client.get(url).get_json()["configuration"]
    first = client.put(
        url,
        json={"configuration": configuration, "expected_version": 0},
        headers=auth_headers(csrf),
    )
    assert first.status_code == 200
    assert first.get_json()["configuration"]["approval_notification_enabled"] is True
    assert "{date}" in first.get_json()["configuration"]["approval_message_template"]
    stale = client.put(
        url,
        json={"configuration": configuration, "expected_version": 0},
        headers=auth_headers(csrf),
    )
    assert stale.status_code == 409
    assert stale.get_json()["code"] == "configuration_conflict"


def test_configuration_is_isolated_by_tenant(demo_app):
    first = make_business(name="First", slug="first-config")
    second = make_business(name="Second", slug="second-config")
    _owner(first)
    _enable(first.id, "ai_memory")
    _enable(second.id, "ai_memory")
    client, _, _ = login(demo_app, "module-owner@test.local", PASSWORD)
    denied = client.get(f"/api/dashboard/businesses/{second.id}/ai-memory/configuration")
    assert denied.status_code == 403
