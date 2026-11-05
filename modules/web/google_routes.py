"""Client-owned Google Connect endpoints."""

from __future__ import annotations

from flask import Blueprint, g, jsonify, redirect, request
from sqlalchemy import select

from modules import google_connections, google_visibility
from modules.auth.decorators import require_business_access
from modules.db import session_scope
from modules.models import Business, GoogleConnection
from modules.tenancy import record_audit_event

google_bp = Blueprint("google", __name__, url_prefix="/api/google")


def _connection(db, business_id: str):
    return db.execute(select(GoogleConnection).where(GoogleConnection.business_id == business_id)).scalar_one_or_none()


@google_bp.get("/businesses/<business_id>")
@require_business_access()
def connection_status(business_id: str):
    return jsonify(google_connections.serialize(_connection(g.db, business_id))), 200


@google_bp.post("/businesses/<business_id>/connect")
@require_business_access(write=True)
def start_connection(business_id: str):
    if g.db.get(Business, business_id) is None:
        return jsonify({"error": "Business not found."}), 404
    try:
        authorize_url = google_connections.begin(g.db, business_id=business_id, user_id=g.current_user.id)
    except google_connections.GoogleConnectionError as exc:
        return jsonify({"error": str(exc)}), 503
    return jsonify({"authorize_url": authorize_url}), 200


@google_bp.get("/businesses/<business_id>/resources")
@require_business_access()
def connection_resources(business_id: str):
    connection = _connection(g.db, business_id)
    if connection is None:
        return jsonify({"error": "Connect Google before choosing assets."}), 409
    try:
        return jsonify(google_connections.discover(connection)), 200
    except google_connections.GoogleConnectionError as exc:
        return jsonify({"error": str(exc)}), 409


@google_bp.patch("/businesses/<business_id>/selection")
@require_business_access(write=True)
def save_selection(business_id: str):
    connection = _connection(g.db, business_id)
    if connection is None:
        return jsonify({"error": "Connect Google before saving assets."}), 409
    payload = request.get_json(silent=True) or {}
    fields = {}
    try:
        search_property = google_visibility.validate_property(str(payload.get("search_property") or ""))
    except ValueError as exc:
        fields["search_property"] = str(exc)
        search_property = ""
    try:
        profile_url = google_visibility.validate_profile_url(str(payload.get("profile_url") or ""))
    except ValueError as exc:
        fields["profile_url"] = str(exc)
        profile_url = ""
    profile_location = str(payload.get("profile_location") or "").strip()
    if profile_location and not google_visibility.LOCATION_PATTERN.fullmatch(profile_location):
        fields["profile_location"] = "Choose a Business Profile location from the connected Google account."
    ga4_property = str(payload.get("ga4_property") or "").strip()
    if ga4_property and not ga4_property.startswith("properties/"):
        fields["ga4_property"] = "Choose a GA4 property from the connected Google account."
    measurement_id = str(payload.get("ga4_measurement_id") or "").strip().upper()
    if measurement_id and not google_visibility.MEASUREMENT_ID_PATTERN.fullmatch(measurement_id):
        fields["ga4_measurement_id"] = "Use a GA4 Measurement ID such as G-ABC123DEF4."
    if fields:
        return jsonify({"error": "Validation failed.", "fields": fields}), 400
    connection.search_property = search_property or None
    connection.profile_location = profile_location or None
    connection.profile_url = profile_url or None
    connection.ga4_property = ga4_property or None
    connection.ga4_measurement_id = measurement_id or None
    record_audit_event(g.db, action="business.google_connection.selection_update", target_type="business", target_id=business_id, business_id=business_id, actor_user_id=g.current_user.id)
    g.db.commit()
    return jsonify(google_connections.serialize(connection)), 200


@google_bp.delete("/businesses/<business_id>")
@require_business_access(write=True)
def disconnect(business_id: str):
    connection = _connection(g.db, business_id)
    if connection is None:
        return "", 204
    g.db.delete(connection)
    record_audit_event(g.db, action="business.google_connection.disconnect", target_type="business", target_id=business_id, business_id=business_id, actor_user_id=g.current_user.id)
    g.db.commit()
    return "", 204


@google_bp.get("/callback")
def callback():
    if request.args.get("error"):
        return redirect("/?google=declined")
    code = request.args.get("code", "")
    state = request.args.get("state", "")
    if not code or not state:
        return redirect("/?google=invalid")
    db = session_scope()
    try:
        connection = google_connections.complete(db, code=code, state=state)
        record_audit_event(db, action="business.google_connection.connect", target_type="business", target_id=connection.business_id, business_id=connection.business_id, actor_user_id=connection.connected_by_user_id)
        db.commit()
        return redirect(f"/b/{connection.business_id}/settings?google=connected")
    except google_connections.GoogleConnectionError:
        db.rollback()
        return redirect("/?google=failed")
    finally:
        db.close()
