"""Read-only platform diagnostics backed by persisted tenant activity."""

from unittest.mock import patch

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

    assert delivery["metrics"]["submitted"] == 1
    assert delivery["items"][0]["business"]["name"] == business.name
    assert {item["kind"] for item in webhooks["items"]} == {"Inbound SMS", "Voice webhook"}
    assert all(item["business_name"] == business.name for item in webhooks["items"])


def test_admin_can_retry_a_failed_missed_call_once(make_app):
    app_module = make_app(
        MISSED_CALLS_ENABLED="true",
        MISSED_CALL_REQUIRE_ALLOWLIST="true",
        MISSED_CALL_ALLOWLIST="+12145550126",
        MISSED_CALL_MAX_SEND_ATTEMPTS="2",
    )
    business = make_business()
    db = session_scope()
    try:
        event = MissedCallEvent(
            business_id=business.id,
            call_sid="CA-admin-retry",
            caller_phone="+12145550126",
            twilio_number="+18175550142",
            source="missed_call",
            decision="send_failed",
            delivery_status="failed",
            send_attempts=1,
            error_code="send_error",
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        event_id = event.id
    finally:
        db.close()
    client = _admin(app_module)

    with patch("modules.missed_call._send_initial_sms", return_value="SM-admin-retry") as send:
        response = client.post(
            f"/api/admin/businesses/{business.id}/missed-calls/{event_id}/retry",
            headers={"X-CSRF-Token": client.get_cookie("ntx_csrf").value},
        )

    assert response.status_code == 200
    assert response.get_json()["event"]["message_sid"] == "SM-admin-retry"
    assert response.get_json()["event"]["send_attempts"] == 2
    send.assert_called_once()
