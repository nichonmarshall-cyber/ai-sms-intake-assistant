"""Client-owned Google OAuth connections and read-only resource discovery.

This module deliberately keeps OAuth refresh tokens server-side and encrypted.
It never asks a client for a Google password and never returns a token to the
browser. A business can disconnect at any time, which removes NTX access only.
"""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from modules.auth.crypto import hash_token, new_token
from modules.models import GoogleConnection, GoogleOAuthState

SCOPES = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/business.manage",
)
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"


class GoogleConnectionError(RuntimeError):
    pass


def _oauth_config() -> tuple[str, str, str]:
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not client_id or not client_secret or not base_url:
        raise GoogleConnectionError(
            "Google Connect is not configured yet. NTX must set the OAuth client ID, client secret, and public app URL on the server."
        )
    return client_id, client_secret, f"{base_url}/api/google/callback"


def configured() -> bool:
    try:
        _oauth_config()
        _fernet()
        return True
    except GoogleConnectionError:
        return False


def _fernet() -> Fernet:
    raw = os.getenv("GOOGLE_CONNECTION_ENCRYPTION_KEY", "").strip()
    if not raw:
        raise GoogleConnectionError("Google Connect encryption is not configured on the server.")
    try:
        return Fernet(raw.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise GoogleConnectionError("Google Connect encryption key is invalid.") from exc


def encrypt_refresh_token(token: str) -> str:
    return _fernet().encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_refresh_token(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise GoogleConnectionError("The saved Google connection can no longer be decrypted. Reconnect Google.") from exc


def begin(db, *, business_id: str, user_id: str) -> str:
    client_id, _, redirect_uri = _oauth_config()
    state = new_token()
    db.add(GoogleOAuthState(
        state_hash=hash_token(state), business_id=business_id, user_id=user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    ))
    db.commit()
    return f"{AUTHORIZE_URL}?{urlencode({
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': ' '.join(SCOPES),
        'access_type': 'offline',
        'prompt': 'consent',
        'include_granted_scopes': 'true',
        'state': state,
    })}"


def _consume_state(db, state: str) -> GoogleOAuthState:
    row = db.query(GoogleOAuthState).filter_by(state_hash=hash_token(state)).one_or_none()
    now = datetime.now(timezone.utc)
    if row is None or row.used_at is not None or row.expires_at < now:
        raise GoogleConnectionError("This Google setup link expired. Start the connection again from the dashboard.")
    row.used_at = now
    return row


def _exchange_code(code: str) -> dict:
    client_id, client_secret, redirect_uri = _oauth_config()
    response = httpx.post(TOKEN_URL, data={
        "code": code, "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
    }, timeout=15.0)
    if response.status_code >= 400:
        raise GoogleConnectionError("Google did not approve the connection. Try again and choose the business Google account.")
    payload = response.json()
    if not payload.get("refresh_token"):
        raise GoogleConnectionError("Google did not provide persistent access. Reconnect and approve access again.")
    return payload


def _email_from_access_token(token: str) -> str | None:
    response = httpx.get("https://openidconnect.googleapis.com/v1/userinfo", headers={"Authorization": f"Bearer {token}"}, timeout=10.0)
    if response.is_success:
        return (response.json().get("email") or "").lower() or None
    return None


def complete(db, *, code: str, state: str) -> GoogleConnection:
    state_row = _consume_state(db, state)
    token = _exchange_code(code)
    existing = db.query(GoogleConnection).filter_by(business_id=state_row.business_id).one_or_none()
    connection = existing or GoogleConnection(business_id=state_row.business_id, encrypted_refresh_token="")
    connection.connected_by_user_id = state_row.user_id
    connection.connected_email = _email_from_access_token(token.get("access_token", ""))
    connection.encrypted_refresh_token = encrypt_refresh_token(token["refresh_token"])
    connection.granted_scopes = (token.get("scope") or " ".join(SCOPES)).split()
    if existing is None:
        db.add(connection)
    db.commit()
    return connection


def access_token(connection: GoogleConnection) -> str:
    client_id, client_secret, _ = _oauth_config()
    credentials = Credentials(
        token=None, refresh_token=decrypt_refresh_token(connection.encrypted_refresh_token),
        token_uri=TOKEN_URL, client_id=client_id, client_secret=client_secret,
        scopes=list(connection.granted_scopes or SCOPES),
    )
    try:
        credentials.refresh(Request())
    except Exception as exc:
        raise GoogleConnectionError("Google access expired or was revoked. Reconnect Google to restore reporting.") from exc
    if not credentials.token:
        raise GoogleConnectionError("Google did not return an access token. Reconnect Google.")
    return credentials.token


def discover(connection: GoogleConnection) -> dict:
    """Return only resources available to this business's connected account."""
    token = access_token(connection)
    headers = {"Authorization": f"Bearer {token}"}
    resources = {"search_properties": [], "ga4_properties": [], "business_locations": [], "diagnostics": []}
    with httpx.Client(timeout=15.0, headers=headers) as client:
        search = client.get("https://www.googleapis.com/webmasters/v3/sites")
        if search.is_success:
            resources["search_properties"] = [row.get("siteUrl") for row in search.json().get("siteEntry", []) if row.get("siteUrl")]
        summaries = client.get("https://analyticsadmin.googleapis.com/v1beta/accountSummaries")
        if summaries.is_success:
            for account in summaries.json().get("accountSummaries", []):
                for prop in account.get("propertySummaries", []):
                    name = prop.get("property")
                    if name:
                        resources["ga4_properties"].append({"id": name, "name": prop.get("displayName") or name})
        accounts = client.get("https://mybusinessaccountmanagement.googleapis.com/v1/accounts")
        if accounts.is_success:
            for account in accounts.json().get("accounts", []):
                account_name = account.get("name")
                if not account_name:
                    continue
                locations = client.get(f"https://mybusinessbusinessinformation.googleapis.com/v1/{account_name}/locations", params={"readMask": "name,title,storefrontAddress,websiteUri"})
                if locations.is_success:
                    for location in locations.json().get("locations", []):
                        if location.get("name"):
                            # Business Information returns locations/123.  Keep the
                            # parent account so the saved value also works with the
                            # reviews endpoint (accounts/123/locations/456).
                            location_name = location["name"]
                            resources["business_locations"].append({
                                "id": f"{account_name}/{location_name}",
                                "name": location.get("title") or location_name,
                                "website_url": location.get("websiteUri") or "",
                            })
                else:
                    resources["diagnostics"].append(
                        "Google Business Profile locations could not be read. Confirm the Business Information API is enabled for this Google Cloud project, then reconnect Google."
                    )
        else:
            resources["diagnostics"].append(
                "Google Business Profile accounts could not be read. Confirm the Business Account Management API is enabled for this Google Cloud project, then reconnect Google."
            )
    return resources


def ga4_report(connection: GoogleConnection, days: int = 30) -> dict:
    """Read a small, useful GA4 acquisition report for the selected property."""
    if not connection.ga4_property:
        raise GoogleConnectionError("Choose a GA4 property in Google reporting settings first.")
    token = access_token(connection)
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=max(1, min(days, 90)) - 1)
    payload = {
        "dateRanges": [{"startDate": start.isoformat(), "endDate": end.isoformat()}],
        "metrics": [{"name": "sessions"}, {"name": "totalUsers"}, {"name": "eventCount"}],
        "dimensions": [{"name": "sessionSource"}, {"name": "sessionMedium"}],
        "limit": 8,
        "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
    }
    response = httpx.post(
        f"https://analyticsdata.googleapis.com/v1beta/{connection.ga4_property}:runReport",
        headers={"Authorization": f"Bearer {token}"}, json=payload, timeout=15.0,
    )
    if response.status_code >= 400:
        raise GoogleConnectionError("GA4 could not provide reporting data. Confirm the selected property belongs to the connected account.")
    rows = response.json().get("rows", [])
    sources = []
    for row in rows:
        dimensions = [item.get("value", "") for item in row.get("dimensionValues", [])]
        metrics = [item.get("value", "0") for item in row.get("metricValues", [])]
        sources.append({
            "source": " / ".join(part for part in dimensions if part) or "(direct)",
            "sessions": int(float(metrics[0])) if metrics else 0,
            "users": int(float(metrics[1])) if len(metrics) > 1 else 0,
            "events": int(float(metrics[2])) if len(metrics) > 2 else 0,
        })
    return {"period": {"start": start.isoformat(), "end": end.isoformat()}, "sources": sources}


def serialize(connection: GoogleConnection | None) -> dict:
    if connection is None:
        return {"status": "not_connected", "oauth_configured": configured()}
    return {
        "status": "connected", "oauth_configured": configured(),
        "connected_email": connection.connected_email,
        "search_property": connection.search_property or "",
        "ga4_property": connection.ga4_property or "",
        "ga4_measurement_id": connection.ga4_measurement_id or "",
        "profile_location": connection.profile_location or "",
        "profile_url": connection.profile_url or "",
        "updated_at": connection.updated_at.isoformat() if connection.updated_at else None,
    }
