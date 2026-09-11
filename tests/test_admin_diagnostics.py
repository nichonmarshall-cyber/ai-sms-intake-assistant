"""Read-only platform diagnostics backed by persisted tenant activity."""

from modules.db import session_scope
from modules.models import MissedCallEvent, ProcessedMessage
from tests.conftest import login, make_business, make_platform_user
from tests.test_client_conversations import _conversation

PASSWORD = "correct-horse-battery-staple"


def _admin(demo_app):
    make_platform_user(email="admin@ntx.test", password=PASSWORD, platform_role="admin")
    return login(demo_app, "admin@ntx.test", PASSWORD)[0]


def test_conversation_diagnostics_include_business_and_support_filters(demo_app):
    business = make_business()
    _conversation(business.id, phone="+12145550123", name="Diagnostic Customer")
    client = _admin(demo_app)

    body = client.get("/api/admin/conversations?q=diagnostic&state=in_progress").get_json()

    assert body["total"] == 1
    assert body["items"][0]["business"]["id"] == business.id
    assert body["items"][0]["customer_name"] == "Diagnostic Customer"
    assert client.get("/api/admin/conversations?state=made_up").status_code == 400


def test_delivery_and_webhook_diagnostics_use_persisted_ledgers(demo_app):
    business = make_business()
    db = session_scope()
    try:
        db.add(
            ProcessedMessage(
                business_id=business.id,
                message_sid="SMdiagnostic01",
                phone="+12145550124",
                response_body="<Response />",
            )
        )
        db.add(
            MissedCallEvent(
                business_id=business.id,
                call_sid="CAdiagnostic01",
                caller_phone="+12145550125",
                twilio_number="+18175550142",
                source="missed_call",
                decision="message_sent",
                message_sid="SMoutbound01",
            )
        )
        db.commit()
    finally:
        db.close()
    client = _admin(demo_app)

    delivery = client.get("/api/admin/delivery").get_json()
    webhooks = client.get("/api/admin/webhooks").get_json()

    assert delivery["metrics"]["queued"] == 1
    assert delivery["items"][0]["business"]["name"] == business.name
    assert {item["kind"] for item in webhooks["items"]} == {"Inbound SMS", "Voice webhook"}
    assert all(item["business_name"] == business.name for item in webhooks["items"])
