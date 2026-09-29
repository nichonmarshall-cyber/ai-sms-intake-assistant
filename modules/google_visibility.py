"""Read-only, tenant-mapped Search Console and Business Profile reporting."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2.service_account import Credentials as ServiceCredentials

SEARCH_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
BUSINESS_SCOPE = "https://www.googleapis.com/auth/business.manage"
LOCATION_PATTERN = re.compile(r"^accounts/[0-9]+/locations/[0-9]+$")


def validate_property(value: str) -> str:
    property_url = value.strip()
    if not property_url:
        return ""
    if property_url.startswith("sc-domain:"):
        domain = property_url.removeprefix("sc-domain:")
        if re.fullmatch(r"[A-Za-z0-9.-]{3,253}", domain) and "." in domain:
            return property_url.lower()
    else:
        parsed = urlsplit(property_url)
        if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment:
            return property_url
    raise ValueError("Use the exact Search Console property, such as sc-domain:example.com or https://example.com/.")


def validate_location(value: str) -> str:
    location = value.strip()
    if location and not LOCATION_PATTERN.fullmatch(location):
        raise ValueError("Use accounts/123/locations/456 from Google Business Profile.")
    return location


def validate_profile_url(value: str) -> str:
    url = value.strip()
    if url:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.hostname not in {"google.com", "www.google.com", "maps.google.com", "maps.app.goo.gl", "g.page"}:
            raise ValueError("Use a Google Maps or g.page HTTPS listing link.")
    return url


def _search_token() -> str:
    source = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not source:
        raise RuntimeError("Search Console service account is not configured.")
    credentials = (ServiceCredentials.from_service_account_info(json.loads(source), scopes=[SEARCH_SCOPE])
                   if source.startswith("{") else ServiceCredentials.from_service_account_file(Path(source), scopes=[SEARCH_SCOPE]))
    credentials.refresh(Request())
    return credentials.token


def search_console(property_url: str, days: int = 28) -> dict:
    """Aggregate one property and fetch its most-clicked queries; no cross-tenant cache."""
    token = _search_token()
    today = datetime.now(timezone.utc).date()
    # Search Console defaults to finalized data; allow its normal reporting lag.
    end = today - timedelta(days=3)
    start = end - timedelta(days=days - 1)
    endpoint = f"https://www.googleapis.com/webmasters/v3/sites/{quote(property_url, safe='')}/searchAnalytics/query"
    headers = {"Authorization": f"Bearer {token}"}
    base = {"startDate": start.isoformat(), "endDate": end.isoformat(), "type": "web"}
    with httpx.Client(timeout=15.0) as client:
        totals = client.post(endpoint, headers=headers, json={**base, "rowLimit": 1})
        totals.raise_for_status()
        queries = client.post(endpoint, headers=headers, json={**base, "dimensions": ["query"], "rowLimit": 10})
        queries.raise_for_status()
    total_row = (totals.json().get("rows") or [{}])[0]
    return {
        "property": property_url,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "clicks": total_row.get("clicks", 0),
        "impressions": total_row.get("impressions", 0),
        "ctr": total_row.get("ctr", 0),
        "position": total_row.get("position"),
        "queries": [{"query": row["keys"][0], "clicks": row.get("clicks", 0), "impressions": row.get("impressions", 0)}
                    for row in queries.json().get("rows", []) if row.get("keys")],
    }


def _business_token() -> str:
    client_id = os.getenv("GOOGLE_BUSINESS_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_BUSINESS_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("GOOGLE_BUSINESS_REFRESH_TOKEN", "").strip()
    if not all((client_id, client_secret, refresh_token)):
        raise RuntimeError("Business Profile OAuth is not configured.")
    credentials = OAuthCredentials(token=None, refresh_token=refresh_token,
                                   token_uri="https://oauth2.googleapis.com/token",
                                   client_id=client_id, client_secret=client_secret,
                                   scopes=[BUSINESS_SCOPE])
    credentials.refresh(Request())
    return credentials.token


def reviews(location: str) -> dict:
    token = _business_token()
    response = httpx.get(
        f"https://mybusiness.googleapis.com/v4/{location}/reviews",
        headers={"Authorization": f"Bearer {token}"},
        params={"pageSize": 20, "orderBy": "updateTime desc"}, timeout=15.0,
    )
    response.raise_for_status()
    data = response.json()
    return {
        "average_rating": data.get("averageRating"),
        "total_reviews": data.get("totalReviewCount", 0),
        "recent": [{
            "id": row.get("reviewId"),
            "author": (row.get("reviewer") or {}).get("displayName") or "Google user",
            "rating": row.get("starRating"),
            "comment": row.get("comment") or "",
            "updated_at": row.get("updateTime"),
            "reply": (row.get("reviewReply") or {}).get("comment") or "",
        } for row in data.get("reviews", [])],
    }
