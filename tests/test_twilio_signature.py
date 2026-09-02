"""Twilio request-signature validation (X-Twilio-Signature)."""

from twilio.request_validator import RequestValidator


def test_missing_or_invalid_signature_rejected(make_app):
    app_module = make_app(APP_MODE="demo", TWILIO_VALIDATION_BYPASS="false", TWILIO_AUTH_TOKEN="real-secret-token")
    client = app_module.app.test_client()

    data = {"From": "+15555550001", "Body": "hi", "MessageSid": "SM1"}
    resp = client.post("/sms", data=data, headers={"X-Twilio-Signature": "totally-invalid"})
    assert resp.status_code == 403


def test_missing_signature_header_rejected(make_app):
    app_module = make_app(APP_MODE="demo", TWILIO_VALIDATION_BYPASS="false", TWILIO_AUTH_TOKEN="real-secret-token")
    client = app_module.app.test_client()

    data = {"From": "+15555550002", "Body": "hi", "MessageSid": "SM2"}
    resp = client.post("/sms", data=data)
    assert resp.status_code == 403


def test_valid_signature_accepted(make_app):
    auth_token = "real-secret-token"
    app_module = make_app(APP_MODE="demo", TWILIO_VALIDATION_BYPASS="false", TWILIO_AUTH_TOKEN=auth_token)
    client = app_module.app.test_client()

    data = {"From": "+15555550003", "Body": "hi", "MessageSid": "SM3"}
    url = "http://localhost/sms"
    signature = RequestValidator(auth_token).compute_signature(url, data)

    resp = client.post("/sms", data=data, headers={"X-Twilio-Signature": signature})
    assert resp.status_code == 200


def test_bypass_flag_skips_validation(make_app):
    app_module = make_app(APP_MODE="demo", TWILIO_VALIDATION_BYPASS="true", TWILIO_AUTH_TOKEN="whatever")
    client = app_module.app.test_client()

    data = {"From": "+15555550004", "Body": "hi", "MessageSid": "SM4"}
    resp = client.post("/sms", data=data)
    assert resp.status_code == 200


def test_voice_webhook_requires_a_valid_signature(make_app):
    app_module = make_app(APP_MODE="demo", TWILIO_VALIDATION_BYPASS="false", TWILIO_AUTH_TOKEN="real-secret-token")
    client = app_module.app.test_client()

    data = {"From": "+15555550005", "To": "+18173936339", "CallSid": "CA-signature-1"}
    resp = client.post("/voice/missed-call", data=data, headers={"X-Twilio-Signature": "totally-invalid"})

    assert resp.status_code == 403
