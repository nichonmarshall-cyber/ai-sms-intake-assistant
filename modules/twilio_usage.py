"""Account-level Twilio usage reporting for platform administrators."""

from __future__ import annotations

import os

import httpx

DISPLAY_CATEGORIES = {
    "sms": "SMS",
    "sms-messages-carrierfees": "SMS carrier fees",
    "mms": "MMS",
    "mms-messages-carrierfees": "MMS carrier fees",
    "calls": "Voice calls",
    "phonenumbers": "Phone numbers",
    "a2p-registration-fees": "A2P registration fees",
}


def is_configured() -> bool:
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    username = os.getenv("TWILIO_API_KEY_SID", "").strip() or account_sid
    password = os.getenv("TWILIO_API_KEY_SECRET", "").strip() or os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    return bool(account_sid and username and password)


def fetch_usage(period: str = "this_month") -> dict:
    if period not in {"this_month", "last_month"}:
        raise ValueError("Unsupported usage period.")
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    username = os.getenv("TWILIO_API_KEY_SID", "").strip() or account_sid
    password = os.getenv("TWILIO_API_KEY_SECRET", "").strip() or os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    if not account_sid or not username or not password:
        raise RuntimeError("Twilio usage is not configured.")

    resource = "ThisMonth" if period == "this_month" else "LastMonth"
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Usage/Records/{resource}.json"
    response = httpx.get(url, params={"PageSize": 1000}, auth=(username, password), timeout=15.0)
    response.raise_for_status()
    raw_records = response.json().get("usage_records", [])
    by_category = {record.get("category"): record for record in raw_records}

    def number(value):
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    total_record = by_category.get("totalprice") or {}
    categories = []
    for key, label in DISPLAY_CATEGORIES.items():
        record = by_category.get(key)
        if not record:
            continue
        categories.append({
            "key": key,
            "label": label,
            "usage": number(record.get("usage")),
            "usage_unit": record.get("usage_unit"),
            "count": number(record.get("count")),
            "count_unit": record.get("count_unit"),
            "price": number(record.get("price")),
            "price_unit": record.get("price_unit") or "USD",
        })

    return {
        "period": period,
        "start_date": total_record.get("start_date"),
        "end_date": total_record.get("end_date"),
        "total_price": number(total_record.get("price")),
        "currency": total_record.get("price_unit") or "USD",
        "categories": categories,
        "note": "Account-wide Twilio usage; categories are not summed because Twilio can report overlapping parent and child records.",
    }
