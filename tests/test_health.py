"""GET /health liveness check."""


def test_health_endpoint(demo_app):
    client = demo_app.app.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["mode"] == "demo"
