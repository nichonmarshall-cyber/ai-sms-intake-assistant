"""Login throttling lives in Postgres, not process memory."""

from tests.conftest import login, make_platform_user

PASSWORD = "correct-horse-battery-staple"


def test_repeated_failures_for_one_email_are_throttled(demo_app):
    make_platform_user(email="admin@ntx.test", password=PASSWORD)

    for _ in range(5):
        _, _, response = login(demo_app, "admin@ntx.test", "wrong-password")
        assert response.status_code == 401

    _, _, blocked = login(demo_app, "admin@ntx.test", "wrong-password")
    assert blocked.status_code == 429
    assert blocked.headers.get("Retry-After")


def test_throttle_blocks_even_the_correct_password(demo_app):
    """Otherwise an attacker gets unlimited guesses as long as one lands."""
    make_platform_user(email="admin@ntx.test", password=PASSWORD)
    for _ in range(5):
        login(demo_app, "admin@ntx.test", "wrong-password")

    _, _, response = login(demo_app, "admin@ntx.test", PASSWORD)
    assert response.status_code == 429


def test_throttle_is_shared_across_client_instances(demo_app):
    """Each test_client is a separate 'worker'; the counter must be in the DB."""
    make_platform_user(email="admin@ntx.test", password=PASSWORD)
    for _ in range(5):
        client = demo_app.app.test_client()
        client.post("/api/auth/login", json={"email": "admin@ntx.test", "password": "nope"})

    fresh_client = demo_app.app.test_client()
    response = fresh_client.post(
        "/api/auth/login", json={"email": "admin@ntx.test", "password": "nope"}
    )
    assert response.status_code == 429


def test_unrelated_account_is_not_locked_out(demo_app):
    make_platform_user(email="victim@ntx.test", password=PASSWORD)
    make_platform_user(email="other@ntx.test", password=PASSWORD)

    for _ in range(5):
        login(demo_app, "victim@ntx.test", "wrong-password")

    _, _, response = login(demo_app, "other@ntx.test", PASSWORD)
    assert response.status_code == 200
