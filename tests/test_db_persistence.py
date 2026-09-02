"""
Database persistence across new application instances -- i.e. a process
restart must not lose an active session or a completed lead, because
state lives in the database, not in memory.
"""

from unittest.mock import patch

from tests.conftest import send_sms, fake_ai_result
from modules.profiles import PROFILES


def test_session_and_lead_survive_a_simulated_restart(make_app, tmp_path):
    db_url = f"sqlite:///{tmp_path / 'persistence_test.db'}"
    phone = "+15557770001"

    # "Instance 1" -- select a profile and answer one question.
    app_instance_1 = make_app(APP_MODE="demo", DATABASE_URL=db_url)
    send_sms(app_instance_1, phone, "hi")
    send_sms(app_instance_1, phone, "1")

    profile = PROFILES["auto_repair"]
    with patch(
        "modules.openai_helper.get_ai_response",
        return_value=fake_ai_result(profile, extracted_fields={
            **{f.key: None for f in profile.fields}, "customer_name": "Riley",
        }),
    ):
        send_sms(app_instance_1, phone, "my name is Riley")

    # "Restart" -- reload the app module fresh, pointed at the SAME database.
    app_instance_2 = make_app(APP_MODE="demo", DATABASE_URL=db_url)

    from modules.db import session_scope
    from modules.conversation_store import normalize_phone
    from modules.models import ConversationSession
    from sqlalchemy import select

    db = session_scope()
    try:
        session = db.execute(
            select(ConversationSession).where(ConversationSession.phone == normalize_phone(phone))
        ).scalar_one()
        assert session.profile_key == "auto_repair"
        assert session.fields.get("customer_name") == "Riley"
    finally:
        db.close()

    # Conversation continues seamlessly on the "new instance".
    code, body = send_sms(app_instance_2, phone, "still here")
    assert code == 200
