"""Client conversation timelines are tenant-scoped and expose only stored messages."""

from datetime import datetime, timedelta, timezone

from modules.db import session_scope
from modules.models import ConversationSession
from tests.conftest import login, make_business, make_membership, make_platform_user

PASSWORD = "correct-horse-battery-staple"


def _conversation(
    business_id: str,
    *,
    phone: str,
    name: str,
    state: str = "in_progress",
    minutes_ago: int = 0,
) -> ConversationSession:
    now = datetime.now(timezone.utc)
    db = session_scope()
    try:
        row = ConversationSession(
            business_id=business_id,
            phone=phone,
            state=state,
            profile_key="auto_repair",
            history=[
                {"role": "user", "content": "My brakes are squeaking."},
                {"role": "assistant", "content": "What is your name?"},
                {"role": "user", "content": name},
                {"role": "system", "content": "This internal item must not leave the API."},
            ],
            fields={
                "name": name,
                "service_request": "Brake inspection",
                "__pending_vehicle_confirmation": {"year": "2018"},
            },
            turn_count=1,
            off_topic_strikes=0,
            terminated=False,
            opted_out=False,
            created_at=now - timedelta(minutes=minutes_ago + 5),
            updated_at=now - timedelta(minutes=minutes_ago),
            expires_at=now + timedelta(minutes=45),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


def _member_business():
    business = make_business()
    user = make_platform_user(
        email="owner@miller.test", password=PASSWORD, platform_role="none"
    )
    make_membership(business.id, user.id, role="owner")
    return business


def test_conversation_list_is_searchable_filterable_and_newest_first(demo_app):
    business = _member_business()
    older = _conversation(
        business.id,
        phone="+12145550101",
        name="Jason Carter",
        state="completed",
        minutes_ago=20,
    )
    newer = _conversation(
        business.id,
        phone="+12145550102",
        name="Sarah Mitchell",
        minutes_ago=2,
    )
    client, _, _ = login(demo_app, "owner@miller.test", PASSWORD)

    listed = client.get(f"/api/dashboard/businesses/{business.id}/conversations").get_json()
    searched = client.get(
        f"/api/dashboard/businesses/{business.id}/conversations?q=jason"
    ).get_json()
    filtered = client.get(
        f"/api/dashboard/businesses/{business.id}/conversations?state=in_progress&page_size=1"
    ).get_json()

    assert [item["id"] for item in listed["items"]] == [newer.id, older.id]
    assert searched["total"] == 1
    assert searched["items"][0]["customer_name"] == "Jason Carter"
    assert searched["items"][0]["last_message"] == "Jason Carter"
    assert searched["items"][0]["message_count"] == 3
    assert filtered["total"] == 1
    assert filtered["items"][0]["state"] == "in_progress"


def test_conversation_detail_sanitizes_history_and_private_fields(demo_app):
    business = _member_business()
    row = _conversation(business.id, phone="+12145550101", name="Jason Carter")
    client, _, _ = login(demo_app, "owner@miller.test", PASSWORD)

    response = client.get(
        f"/api/dashboard/businesses/{business.id}/conversations/{row.id}"
    )

    assert response.status_code == 200
    conversation = response.get_json()["conversation"]
    assert conversation["messages"] == [
        {"role": "user", "content": "My brakes are squeaking."},
        {"role": "assistant", "content": "What is your name?"},
        {"role": "user", "content": "Jason Carter"},
    ]
    assert conversation["collected_fields"] == {
        "name": "Jason Carter",
        "service_request": "Brake inspection",
    }
    assert "__pending_vehicle_confirmation" not in str(conversation)


def test_conversation_endpoints_never_cross_tenant_boundaries(demo_app):
    mine = _member_business()
    theirs = make_business(name="North Texas Roofing", slug="ntx-roofing")
    _conversation(mine.id, phone="+12145550101", name="Mine")
    other = _conversation(theirs.id, phone="+19725550101", name="Theirs")
    client, _, _ = login(demo_app, "owner@miller.test", PASSWORD)

    listed = client.get(f"/api/dashboard/businesses/{mine.id}/conversations").get_json()
    detail = client.get(
        f"/api/dashboard/businesses/{mine.id}/conversations/{other.id}"
    )

    assert [item["customer_name"] for item in listed["items"]] == ["Mine"]
    assert detail.status_code == 404


def test_invalid_conversation_state_is_rejected(demo_app):
    business = _member_business()
    client, _, _ = login(demo_app, "owner@miller.test", PASSWORD)

    response = client.get(
        f"/api/dashboard/businesses/{business.id}/conversations?state=not-real"
    )

    assert response.status_code == 400


def test_overview_reports_open_conversations_from_real_sessions(demo_app):
    business = _member_business()
    _conversation(business.id, phone="+12145550101", name="Active")
    _conversation(
        business.id,
        phone="+12145550102",
        name="Finished",
        state="completed",
    )
    client, _, _ = login(demo_app, "owner@miller.test", PASSWORD)

    metrics = client.get(
        f"/api/dashboard/businesses/{business.id}/overview"
    ).get_json()["metrics"]

    assert metrics["open_conversations"] == 1
