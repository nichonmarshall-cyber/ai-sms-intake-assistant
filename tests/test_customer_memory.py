"""Customer memory stays tenant-scoped and proposals need a human decision."""

from modules import entitlements
from modules.db import session_scope
from modules.models import CustomerMemory, CustomerMemoryRecord
from tests.conftest import auth_headers, login, make_business, make_membership, make_platform_user

PASSWORD = "correct-horse-battery-staple"


def _owner(business, email="memory-owner@test.local"):
    user = make_platform_user(email=email, password=PASSWORD, platform_role="none")
    make_membership(business.id, user.id, role="owner")
    db = session_scope()
    try:
        entitlements.set_module(db, business.id, "ai_memory", True)
        db.commit()
    finally:
        db.close()
    return user


def _config(client, csrf, business):
    url = f"/api/dashboard/businesses/{business.id}/ai-memory/configuration"
    body = client.get(url).get_json()
    config = body["configuration"]
    config["record_types"] = [{
        "key": "asset", "label": "Asset", "fields": [
            {"key": "serial", "label": "Serial", "type": "text", "ai_visibility": "proposed_update", "update_authority": "ai_proposal", "sensitivity": "standard"},
            {"key": "secret", "label": "Secret", "type": "text", "ai_visibility": "hidden", "update_authority": "employee_only", "sensitivity": "restricted"},
        ],
    }]
    assert client.put(url, json={"configuration": config, "expected_version": body["version"]}, headers=auth_headers(csrf)).status_code == 200


def test_memory_records_and_proposals_are_scoped_and_approved(demo_app):
    first = make_business(name="First", slug="memory-first")
    second = make_business(name="Second", slug="memory-second")
    _owner(first)
    db = session_scope()
    try:
        entitlements.set_module(db, second.id, "ai_memory", True)
        db.commit()
    finally:
        db.close()
    client, csrf, _ = login(demo_app, "memory-owner@test.local", PASSWORD)
    _config(client, csrf, first)
    base = f"/api/dashboard/businesses/{first.id}/ai-memory"
    created = client.post(f"{base}/customers", json={"phone": "+12145550101", "customer_name": "Milo Owner"}, headers=auth_headers(csrf))
    assert created.status_code == 201
    customer_id = created.get_json()["customer"]["id"]
    record = client.post(f"{base}/customers/{customer_id}/records", json={"record_type": "asset", "label": "Unit A", "values": {"serial": "A-22", "secret": "employee only"}}, headers=auth_headers(csrf))
    assert record.status_code == 201
    record_id = record.get_json()["record"]["id"]

    # Directly use the proposal service as the intake-side caller would; the
    # dashboard can only approve/reject it, never silently apply it.
    from modules.customer_memory import propose_update
    db = session_scope()
    try:
        customer = db.get(CustomerMemory, customer_id)
        proposal = propose_update(db, customer, {"record_id": record_id, "record_type": "asset", "proposed_values": {"serial": "A-23"}, "reason": "Customer reported the replacement label."})
        db.commit()
        proposal_id = proposal.id
    finally:
        db.close()
    detail = client.get(f"{base}/customers/{customer_id}")
    assert detail.status_code == 200
    assert detail.get_json()["context_packet"]["records"][0]["values"] == {"serial": "A-22"}
    assert client.patch(f"{base}/proposals/{proposal_id}", json={"action": "approve"}, headers=auth_headers(csrf)).status_code == 200
    db = session_scope()
    try:
        assert db.get(CustomerMemoryRecord, record_id).values["serial"] == "A-23"
    finally:
        db.close()
    assert client.get(f"/api/dashboard/businesses/{second.id}/ai-memory/customers").status_code == 403


def test_ai_cannot_propose_hidden_or_employee_only_fields(demo_app):
    business = make_business(slug="memory-guard")
    _owner(business)
    client, csrf, _ = login(demo_app, "memory-owner@test.local", PASSWORD)
    _config(client, csrf, business)
    from modules.customer_memory import MemoryValidationError, get_or_create_customer, propose_update
    db = session_scope()
    try:
        customer = get_or_create_customer(db, business.id, "+12145550102")
        try:
            propose_update(db, customer, {"record_type": "asset", "proposed_values": {"secret": "nope"}})
            assert False, "restricted fields must be rejected"
        except MemoryValidationError:
            pass
    finally:
        db.close()
