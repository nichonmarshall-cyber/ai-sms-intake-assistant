"""Login, logout, and session introspection."""

from __future__ import annotations

import logging

from flask import Blueprint, g, jsonify, request
from sqlalchemy import select

from modules.auth import passwords, sessions, throttle
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
