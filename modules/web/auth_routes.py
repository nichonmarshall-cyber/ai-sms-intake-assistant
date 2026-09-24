"""Login, logout, and session introspection."""

from __future__ import annotations

import logging

from flask import Blueprint, g, jsonify, request
from sqlalchemy import select

from modules.auth import mailer, password_reset, passwords, sessions, throttle
from modules.auth.decorators import (
    client_ip,
    is_platform_admin,
    is_platform_staff,
    memberships_for,
    platform_role,
    require_auth,
)
from modules.db import session_scope
from modules.models import Business, PlatformUser
from modules.serializers import user_dto
from modules.tenancy import record_audit_event

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

GENERIC_LOGIN_FAILURE = "Invalid email or password."


@auth_bp.post("/login")
def login():
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip()
    password = payload.get("password") or ""
    raw_ip = client_ip()

    db = session_scope()
    try:
        decision = throttle.check(db, email=email, raw_ip=raw_ip)
        if not decision.allowed:
            logger.warning("[auth] Throttled login attempt for %s", email[:3] + "***")
            response = jsonify({"error": "Too many attempts. Try again later."})
            response.headers["Retry-After"] = str(decision.retry_after_seconds)
            return response, 429

        user = db.execute(
            select(PlatformUser).where(PlatformUser.email == email.lower())
        ).scalar_one_or_none()

        if user is None:
            # Spend equivalent scrypt work so response time does not reveal
            # whether this email is registered.
            passwords.burn_dummy_verification(password)
            throttle.record(db, email=email, raw_ip=raw_ip, success=False)
            return jsonify({"error": GENERIC_LOGIN_FAILURE}), 401

        if not passwords.verify_password(user.password_hash, password) or not user.is_active:
            throttle.record(db, email=email, raw_ip=raw_ip, success=False)
            return jsonify({"error": GENERIC_LOGIN_FAILURE}), 401

        throttle.record(db, email=email, raw_ip=raw_ip, success=True)
        issued = sessions.create_session(
            db,
            user_id=user.id,
            raw_ip=raw_ip,
            user_agent=request.headers.get("User-Agent"),
        )
        record_audit_event(
            db,
            action="auth.login",
            target_type="platform_user",
            target_id=user.id,
            actor_user_id=user.id,
        )
        db.commit()
        sessions.maybe_purge(db)

        response = jsonify({"user": user_dto(user)})
        sessions.set_auth_cookies(response, issued)
        return response, 200
    finally:
        db.close()


@auth_bp.post("/logout")
@require_auth
def logout():
    record_audit_event(
        g.db,
        action="auth.logout",
        target_type="platform_user",
        target_id=g.current_user.id,
        actor_user_id=g.current_user.id,
    )
    sessions.revoke_session(g.db, g.current_session)
    g.db.commit()

    response = jsonify({"status": "ok"})
    sessions.clear_auth_cookies(response)
    return response, 200


@auth_bp.get("/me")
@require_auth
def me():
    """Identity plus the businesses this user may actually reach."""
    user = g.current_user
    role = platform_role(user)

    if is_platform_admin(user) or is_platform_staff(user):
        businesses = list(g.db.execute(select(Business).order_by(Business.name)).scalars())
        accessible = [
            {"id": b.id, "name": b.name, "slug": b.slug, "role": f"platform_{role}"}
            for b in businesses
        ]
    else:
        accessible = []
        for membership in memberships_for(g.db, user.id):
            business = g.db.get(Business, membership.business_id)
            if business is None:
                continue
            accessible.append(
                {
                    "id": business.id,
                    "name": business.name,
                    "slug": business.slug,
                    "role": membership.role,
                }
            )

    return jsonify(
        {
            "user": user_dto(user),
            "businesses": accessible,
            "can_access_control_center": is_platform_admin(user) or is_platform_staff(user),
            "is_read_only": is_platform_staff(user),
        }
    ), 200


@auth_bp.post("/change-password")
@require_auth
def change_password():
    payload = request.get_json(silent=True) or {}
    current_password = payload.get("current_password") or ""
    new_password = payload.get("new_password") or ""
    user = g.current_user

    errors = {}
    if not passwords.verify_password(user.password_hash, current_password):
        errors["current_password"] = "The current password is incorrect."
    strength_error = passwords.validate_password_strength(new_password)
    if strength_error:
        errors["new_password"] = strength_error
    elif passwords.verify_password(user.password_hash, new_password):
        errors["new_password"] = "Choose a password you have not already been using."
    if errors:
        return jsonify({"error": "Validation failed.", "fields": errors}), 400

    user.password_hash = passwords.hash_password(new_password)
    user.must_change_password = False
    record_audit_event(
        g.db,
        action="auth.password.change",
        target_type="platform_user",
        target_id=user.id,
        actor_user_id=user.id,
    )
    g.db.commit()
    sessions.revoke_all_for_user(g.db, user.id)
    response = jsonify({"status": "ok", "message": "Password changed. Sign in again."})
    sessions.clear_auth_cookies(response)
    return response, 200


@auth_bp.post("/password-reset/request")
def request_password_reset():
    """Always returns the same response so account existence is not disclosed."""
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    generic = {
        "status": "ok",
        "message": "If that account exists, a reset link will be sent shortly.",
    }
    db = session_scope()
    try:
        # Keep the dominant KDF cost present for both registered and unknown
        # addresses so response timing does not become an account oracle.
        passwords.burn_dummy_verification("")
        user = db.execute(select(PlatformUser).where(PlatformUser.email == email)).scalar_one_or_none()
        if user is None or not user.is_active:
            return jsonify(generic), 202
        if password_reset.rate_limited(db, user_id=user.id, raw_ip=client_ip()):
            return jsonify(generic), 202

        raw_token = password_reset.issue(db, user_id=user.id, raw_ip=client_ip())
        record_audit_event(
            db,
            action="auth.password_reset.request",
            target_type="platform_user",
            target_id=user.id,
            actor_user_id=None,
        )
        db.commit()
        mailer.send_password_reset(recipient=user.email, token=raw_token)
        return jsonify(generic), 202
    finally:
        db.close()


@auth_bp.post("/password-reset/confirm")
def confirm_password_reset():
    payload = request.get_json(silent=True) or {}
    token = payload.get("token") or ""
    new_password = payload.get("new_password") or ""
    strength_error = passwords.validate_password_strength(new_password)
    if strength_error:
        return jsonify({"error": "Validation failed.", "fields": {"new_password": strength_error}}), 400

    db = session_scope()
    try:
        token_row = password_reset.consume(db, token)
        if token_row is None:
            db.commit()
            return jsonify({"error": "This reset link is invalid or has expired."}), 400
        user = db.get(PlatformUser, token_row.user_id)
        if user is None or not user.is_active:
            db.commit()
            return jsonify({"error": "This reset link is invalid or has expired."}), 400
        if passwords.verify_password(user.password_hash, new_password):
            return jsonify({"error": "Choose a password you have not already been using."}), 400

        user.password_hash = passwords.hash_password(new_password)
        user.must_change_password = False
        record_audit_event(
            db,
            action="auth.password_reset.complete",
            target_type="platform_user",
            target_id=user.id,
            actor_user_id=user.id,
        )
        db.commit()
        sessions.revoke_all_for_user(db, user.id)
        return jsonify({"status": "ok", "message": "Password reset. You can sign in now."}), 200
    finally:
        db.close()
