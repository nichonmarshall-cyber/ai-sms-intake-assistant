"""UptimeRobot-backed website health for the platform dashboard."""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit

import httpx

UPTIMEROBOT_V2_URL = "https://api.uptimerobot.com/v2/getMonitors"
STATUS_LABELS = {
    0: "paused",
    1: "not_checked",
    2: "up",
    8: "seems_down",
    9: "down",
}


def is_configured() -> bool:
    return bool(os.getenv("UPTIMEROBOT_API_KEY", "").strip())


def normalize_url(value: str) -> str:
    """Validate and normalize an HTTP(S) URL stored for a business."""
    raw = (value or "").strip()
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Enter a complete http:// or https:// website URL.")
    if parsed.username or parsed.password:
        raise ValueError("Website URLs cannot contain credentials.")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, "", ""))


def list_monitors() -> list[dict]:
    api_key = os.getenv("UPTIMEROBOT_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("UptimeRobot is not configured.")

    response = httpx.post(
        UPTIMEROBOT_V2_URL,
        data={
            "api_key": api_key,
            "format": "json",
            "custom_uptime_ratios": "7-30-90",
            "response_times": "1",
            "response_times_average": "30",
        },
        timeout=15.0,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("stat") != "ok":
        raise RuntimeError("UptimeRobot returned an unsuccessful response.")

    monitors = []
    for item in payload.get("monitors", []):
        ratios = str(item.get("custom_uptime_ratio") or "").split("-")
        response_times = item.get("response_times") or []
        average_ms = None
        if response_times:
            values = [row.get("value") for row in response_times if row.get("value") is not None]
            average_ms = round(sum(values) / len(values)) if values else None
        monitors.append({
            "id": str(item.get("id")),
            "name": item.get("friendly_name") or item.get("url") or "Website",
            "url": item.get("url") or "",
            "status": STATUS_LABELS.get(item.get("status"), "unknown"),
            "uptime_7d": ratios[0] if len(ratios) > 0 else None,
            "uptime_30d": ratios[1] if len(ratios) > 1 else None,
            "uptime_90d": ratios[2] if len(ratios) > 2 else None,
            "average_response_ms": average_ms,
        })
    return monitors
