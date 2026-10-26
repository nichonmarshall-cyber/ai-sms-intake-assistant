from tests.conftest import auth_headers


def test_demo_login_creates_a_read_only_fictional_workspace(demo_app):
    client = demo_app.app.test_client()
    response = client.post("/api/auth/demo")

    assert response.status_code == 200
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    payload = me.get_json()
    assert payload["user"]["display_name"] == "Product Demo"
    assert payload["businesses"] == [{
        "id": "ntx-product-demo",
        "name": "Northstar Auto Care — Demo",
        "slug": "northstar-auto-care-demo",
        "role": "viewer",
    }]

    overview = client.get("/api/dashboard/businesses/ntx-product-demo/overview")
    assert overview.status_code == 200
    assert overview.get_json()["metrics"]["total_leads"] == 5

    csrf = next(value.split(";", 1)[0] for value in response.headers.getlist("Set-Cookie") if value.startswith("ntx_csrf=")).split("=", 1)[1]
    write = client.patch("/api/dashboard/businesses/ntx-product-demo/leads/1", json={"workflow_status": "closed"}, headers=auth_headers(csrf))
    assert write.status_code == 403
