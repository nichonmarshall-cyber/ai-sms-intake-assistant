"""A Google Sheets export failure must never crash the webhook or lose the lead."""

from unittest.mock import patch

from tests.conftest import send_sms, fake_ai_result
from modules.profiles import PROFILES
from modules import sheets_helper


def test_sheets_disabled_does_not_touch_google(demo_app):
    phone = "+15559990001"
    send_sms(demo_app, phone, "hi")
    send_sms(demo_app, phone, "1")
    profile = PROFILES["auto_repair"]

    complete_fields = {f.key: "answer" for f in profile.fields}

    with patch("modules.openai_helper.get_ai_response", return_value=fake_ai_result(
        profile, extracted_fields=complete_fields, is_complete=True,
        should_terminate=True, termination_reason="completed",
    )), patch.object(sheets_helper, "_get_workbook") as mock_workbook:
        code, body = send_sms(demo_app, phone, "final answer")

    assert code == 200
    mock_workbook.assert_not_called()


def test_sheets_enabled_but_connection_fails_does_not_break_webhook(make_app):
    app_module = make_app(
        APP_MODE="demo", SHEETS_ENABLED="true",
        GOOGLE_SERVICE_ACCOUNT_JSON="credentials/service_account.json",
        GOOGLE_SHEET_ID="fake-sheet-id",
    )
    phone = "+15559990002"
    send_sms(app_module, phone, "hi")
    send_sms(app_module, phone, "1")
    profile = PROFILES["auto_repair"]
    complete_fields = {f.key: "answer" for f in profile.fields}

    with patch("modules.openai_helper.get_ai_response", return_value=fake_ai_result(
        profile, extracted_fields=complete_fields, is_complete=True,
        should_terminate=True, termination_reason="completed",
    )), patch.object(sheets_helper, "_get_workbook", side_effect=RuntimeError("Google is down")):
        code, body = send_sms(app_module, phone, "final answer")

    assert code == 200  # webhook survives even though Sheets export failed

    from modules.db import session_scope
    from modules.conversation_store import normalize_phone
    from modules.models import Lead
    from sqlalchemy import select

    db = session_scope()
    try:
        lead = db.execute(select(Lead).where(Lead.phone == normalize_phone(phone))).scalar_one()
        assert lead is not None  # Postgres/SQLite lead is safe regardless of Sheets
    finally:
        db.close()
