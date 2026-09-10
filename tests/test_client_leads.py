"""Client lead management uses real rows and enforces tenant boundaries."""

from sqlalchemy import select

from modules.db import session_scope
from modules.models import AuditEvent, Lead
from tests.conftest import (
    auth_headers,
    login,
    make_business,
    make_membership,
    make_platform_user,
)

PASSWORD = "correct-horse-battery-staple"


def _lead(business_id: str, *, name: str, phone: str, status: str = "new") -> Lead:
    db = session_scope()
    try:
        lead = Lead(
            business_id=business_id,
            phone=phone,
            profile_key="auto_repair",
            fields={"name": name, "service_request": "Brake inspection", "source": "sms"},
            status="completed",
            workflow_status=status,
            category="service",
            business_summary=f"{name} requested a brake inspection.",
            is_complete=True,
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)
        return lead
    finally:
        db.close()


def _client_with_business(*, role: str = "owner"):
    business = make_business()
    user = make_platform_user(
        email=f"{role}@miller.test", password=PASSWORD, platform_role="none"
    )
    make_membership(business.id, user.id, role=role)
    return business, login


def test_leads_are_listed_newest_first_and_serialized(demo_app):
    business, _ = _client_with_business()
    older = _lead(business.id, name="Jason Carter", phone="+12145550101")
    newer = _lead(business.id, name="Sarah Mitchell", phone="+12145550102", status="qualified")
    client, _, _ = login(demo_app, "owner@miller.test", PASSWORD)

    response = client.get(f"/api/dashboard/businesses/{business.id}/leads")

    assert response.status_code == 200
    body = response.get_json()
    assert body["total"] == 2
    assert [item["id"] for item in body["items"]] == [newer.id, older.id]
    assert body["items"][0]["customer_name"] == "Sarah Mitchell"
    assert body["items"][0]["service_request"] == "Brake inspection"
    assert "password_hash" not in body["items"][0]


def test_leads_support_search_status_and_pagination(demo_app):
    business, _ = _client_with_business()
    _lead(business.id, name="Jason Carter", phone="+12145550101")
    _lead(business.id, name="Sarah Mitchell", phone="+12145550102", status="qualified")
    client, _, _ = login(demo_app, "owner@miller.test", PASSWORD)

    by_name = client.get(f"/api/dashboard/businesses/{business.id}/leads?q=sarah").get_json()
    by_status = client.get(
        f"/api/dashboard/businesses/{business.id}/leads?status=qualified&page_size=1"
    ).get_json()

    assert by_name["total"] == 1
    assert by_name["items"][0]["customer_name"] == "Sarah Mitchell"
    assert by_status["total"] == 1
    assert by_status["page_size"] == 1


def test_leads_never_cross_tenant_boundaries(demo_app):
    mine, _ = _client_with_business()
    theirs = make_business(name="North Texas Roofing", slug="ntx-roofing")
    _lead(mine.id, name="Mine", phone="+12145550101")
    other = _lead(theirs.id, name="Theirs", phone="+19725550101")
    client, csrf, _ = login(demo_app, "owner@miller.test", PASSWORD)

    listed = client.get(f"/api/dashboard/businesses/{mine.id}/leads").get_json()
    update = client.patch(
        f"/api/dashboard/businesses/{mine.id}/leads/{other.id}",
        json={"workflow_status": "closed"},
        headers=auth_headers(csrf),
    )

    assert [item["customer_name"] for item in listed["items"]] == ["Mine"]
    assert update.status_code == 404


def test_owner_can_update_notes_status_and_archive_without_deleting(demo_app):
    business, _ = _client_with_business()
    lead = _lead(business.id, name="Jason Carter", phone="+12145550101")
    client, csrf, _ = login(demo_app, "owner@miller.test", PASSWORD)

    updated = client.patch(
        f"/api/dashboard/businesses/{business.id}/leads/{lead.id}",
        json={"workflow_status": "scheduled", "client_notes": "Booked for Friday."},
        headers=auth_headers(csrf),
    )
    archived = client.patch(
        f"/api/dashboard/businesses/{business.id}/leads/{lead.id}",
        json={"archive": True},
        headers=auth_headers(csrf),
    )

    assert updated.status_code == 200
    assert updated.get_json()["lead"]["workflow_status"] == "scheduled"
    assert archived.status_code == 200
    assert archived.get_json()["lead"]["archived_at"] is not None
    assert client.get(f"/api/dashboard/businesses/{business.id}/leads").get_json()["total"] == 0
    assert client.get(
        f"/api/dashboard/businesses/{business.id}/leads?include_archived=true"
    ).get_json()["total"] == 1

    restored = client.patch(
        f"/api/dashboard/businesses/{business.id}/leads/{lead.id}",
        json={"archive": False},
        headers=auth_headers(csrf),
    )
    assert restored.status_code == 200
    assert restored.get_json()["lead"]["archived_at"] is None
    assert client.get(f"/api/dashboard/businesses/{business.id}/leads").get_json()["total"] == 1

    db = session_scope()
    try:
        assert db.get(Lead, lead.id) is not None
        actions = list(
            db.execute(
                select(AuditEvent.action).where(
                    AuditEvent.business_id == business.id,
                    AuditEvent.target_id == str(lead.id),
                )
            ).scalars()
        )
    finally:
        db.close()
    assert actions == ["lead.update", "lead.update", "lead.update"]


def test_viewer_can_read_leads_but_cannot_change_them(demo_app):
    business, _ = _client_with_business(role="viewer")
    lead = _lead(business.id, name="Jason Carter", phone="+12145550101")
    client, csrf, _ = login(demo_app, "viewer@miller.test", PASSWORD)

    assert client.get(f"/api/dashboard/businesses/{business.id}/leads").status_code == 200
    response = client.patch(
        f"/api/dashboard/businesses/{business.id}/leads/{lead.id}",
        json={"workflow_status": "closed"},
        headers=auth_headers(csrf),
    )
    assert response.status_code == 403
