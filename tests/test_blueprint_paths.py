"""The webhook and system routes must not move, and the SPA must not shadow them.

These are the regression guards for the live Render deployment: if blueprint
registration ever starts capturing /sms, Twilio breaks silently.
"""

from tests.conftest import send_sms


def test_existing_routes_are_registered_at_their_original_paths(demo_app):
    rules = {r.rule: sorted(r.methods - {"HEAD", "OPTIONS"}) for r in demo_app.app.url_map.iter_rules()}

    assert rules.get("/sms") == ["POST"]
    assert rules.get("/voice/missed-call") == ["POST"]
    assert rules.get("/health") == ["GET"]
    assert rules.get("/reset") == ["POST"]


def test_sms_route_is_owned_by_app_not_a_blueprint(demo_app):
    endpoints = {r.rule: r.endpoint for r in demo_app.app.url_map.iter_rules()}
    # No blueprint prefix means the original handler is still the one serving it.
    assert "." not in endpoints["/sms"]
    assert "." not in endpoints["/voice/missed-call"]
    assert "." not in endpoints["/health"]


def test_sms_webhook_still_returns_twiml(demo_app):
    status, body = send_sms(demo_app, "+15125550188", "hi")
    assert status == 200
    assert body.startswith("<?xml")


def test_health_payload_unchanged(demo_app):
    body = demo_app.app.test_client().get("/health").get_json()
    assert body["service"] == "sms-intake-assistant"
    assert body["mode"] == "demo"
    assert "tenant_routing" in body


def test_spa_catch_all_does_not_swallow_api_paths(demo_app):
    """An unauthenticated API call must 401, never fall through to the SPA."""
    response = demo_app.app.test_client().get("/api/auth/me")
    assert response.status_code == 401


def test_dashboard_returns_controlled_503_when_bundle_is_absent(demo_app, monkeypatch):
    """This is exactly the state of the Render deployment during Phase 1a."""
    from modules.web import spa

    monkeypatch.setattr(spa, "INDEX_FILE", "/nonexistent/index.html")
    assert spa.dashboard_available() is False

    response = demo_app.app.test_client().get("/")
    assert response.status_code == 503
    assert "not built" in response.get_json()["error"]


def test_webhooks_keep_working_while_the_dashboard_is_unavailable(demo_app, monkeypatch):
    """A missing frontend bundle must never affect Twilio or health checks."""
    from modules.web import spa

    monkeypatch.setattr(spa, "INDEX_FILE", "/nonexistent/index.html")
    assert demo_app.app.test_client().get("/").status_code == 503

    status, _ = send_sms(demo_app, "+15125550199", "hello")
    assert status == 200
    assert demo_app.app.test_client().get("/health").status_code == 200


def test_dashboard_is_served_when_the_bundle_has_been_built(demo_app, tmp_path, monkeypatch):
    """The same-origin bundle path, exercised without needing a real build."""
    from modules.web import spa

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")

    monkeypatch.setattr(spa, "DIST_DIR", str(dist))
    monkeypatch.setattr(spa, "INDEX_FILE", str(dist / "index.html"))

    response = demo_app.app.test_client().get("/")
    assert response.status_code == 200
    assert b"id=root" in response.data


def test_spa_route_never_captures_the_sms_webhook(demo_app, tmp_path, monkeypatch):
    """Even with a built bundle present, Twilio's path must not be swallowed."""
    from modules.web import spa

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>")
    monkeypatch.setattr(spa, "DIST_DIR", str(dist))
    monkeypatch.setattr(spa, "INDEX_FILE", str(dist / "index.html"))

    status, body = send_sms(demo_app, "+15125550177", "hello")
    assert status == 200
    assert body.startswith("<?xml")


def test_reset_endpoint_still_gated(demo_app):
    response = demo_app.app.test_client().post("/reset", json={})
    assert response.status_code == 404
