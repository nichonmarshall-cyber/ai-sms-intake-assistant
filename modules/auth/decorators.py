"""Request-scoped authentication and authorization.

Authorization rules, stated once so they are not re-derived per route:

* A platform ADMIN bypasses membership checks entirely.
* A platform STAFF user has explicit READ-ONLY cross-tenant access. Staff never
  get writes and never reach admin management routes. Broader staff powers are
  a deliberate future change, not an implicit default.
* Everyone else -- including client owners -- has exactly the access granted by
  a row in ``business_memberships``. A ``business_id`` from the browser is only
  ever used to SELECT AMONG businesses the caller already has; it never grants.
"""

from __future__ import annotations

import logging
from functools import wraps

from flask import g, jsonify, request
from sqlalchemy import select

from modules.auth import sessions
from modules.auth.csrf import CSRF_HEADER, is_exempt
from modules.db import session_scope
from modules.models import BusinessMembership

logger = logging.getLogger(__name__)


PLATFORM_ADMIN = "admin"
PLATFORM_STAFF = "staff"

MEMBERSHIP_RANK = {"viewer": 0, "staff": 1, "manager": 2, "owner": 3}
WRITE_MIN_RANK = MEMBERSHIP_RANK["staff"]


def _json_error(message: str, status: int, **extra):
    payload = {"error": message}
    payload.update(extra)
    return jsonify(payload), status


def client_ip() -> str | None:
    """Render terminates TLS at a proxy, so trust the first X-Forwarded-For hop."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr


def platform_role(user) -> str:
    role = (getattr(user, "platform_role", "") or "").strip().lower()
    if role in {PLATFORM_ADMIN, PLATFORM_STAFF}:
        return role
    # Backward compatibility with rows written before platform_role existed.
    return PLATFORM_ADMIN if getattr(user, "is_platform_admin", False) else "none"


def is_platform_admin(user) -> bool:
    return platform_role(user) == PLATFORM_ADMIN


def is_platform_staff(user) -> bool:
    return platform_role(user) == PLATFORM_STAFF


def memberships_for(db, user_id: str) -> list[BusinessMembership]:
    return list(
        db.execute(
            select(BusinessMembership).where(BusinessMembership.user_id == user_id)
        ).scalars()
    )


def require_auth(view):
    """Loads the session, enforces CSRF, and opens a request-scoped DB session."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        db = session_scope()
        try:
            token = request.cookies.get(sessions.SESSION_COOKIE_NAME)
            loaded = sessions.load_session(db, token)
            if loaded is None:
                return _json_error("Authentication required.", 401)

            session_row, user = loaded

            if not is_exempt(request.path, request.method):
                presented = request.headers.get(CSRF_HEADER, "")
                if not sessions.verify_csrf(session_row, presented):
                    logger.warning("[auth] CSRF rejection on %s %s", request.method, request.path)
                    return _json_error("Invalid or missing CSRF token.", 403)

            sessions.touch_session(db, session_row)

            g.db = db
            g.current_user = user
            g.current_session = session_row
            return view(*args, **kwargs)
        finally:
            db.close()

    return wrapper


def require_platform_admin(view):
    @wraps(view)
    @require_auth
    def wrapper(*args, **kwargs):
        if not is_platform_admin(g.current_user):
            logger.warning(
                "[authz] Non-admin user %s attempted %s", g.current_user.id, request.path
            )
            return _json_error("Administrator access required.", 403)
        return view(*args, **kwargs)

    return wrapper


def require_business_access(*, write: bool = False):
    """Resolves and authorizes ``business_id`` from the route's path arguments."""

    def decorator(view):
        @wraps(view)
        @require_auth
        def wrapper(*args, **kwargs):
            business_id = kwargs.get("business_id") or request.view_args.get("business_id")
            if not business_id:
                return _json_error("A business is required.", 400)

            user = g.current_user

            if is_platform_admin(user):
                g.business_role = "platform_admin"
                return view(*args, **kwargs)

            if is_platform_staff(user):
                if write:
                    # Explicitly read-only for now. Widening this is a decision,
                    # not something that should happen by omission.
                    return _json_error("Platform staff access is read-only.", 403)
                g.business_role = "platform_staff"
                return view(*args, **kwargs)

            membership = g.db.execute(
                select(BusinessMembership).where(
                    BusinessMembership.user_id == user.id,
                    BusinessMembership.business_id == business_id,
                )
            ).scalar_one_or_none()

            if membership is None:
                logger.warning(
                    "[authz] Cross-tenant denial: user=%s business=%s path=%s",
                    user.id,
                    business_id,
                    request.path,
                )
                # 403, not 404: the caller is authenticated and the denial is
                # recorded. Existence is not leaked because the message is
                # identical whether or not the business exists.
                return _json_error("You do not have access to this business.", 403)

            rank = MEMBERSHIP_RANK.get((membership.role or "").lower(), -1)
            if write and rank < WRITE_MIN_RANK:
                return _json_error("Your role does not allow this change.", 403)

            g.business_role = membership.role
            g.membership = membership
            return view(*args, **kwargs)

        return wrapper

    return decorator


def require_module(module_key: str):
    """Server-side module gate. Hiding a nav link is not authorization."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            from modules import entitlements

            business_id = kwargs.get("business_id") or request.view_args.get("business_id")
            if not entitlements.is_module_enabled(g.db, business_id, module_key):
                return _json_error("This module is not enabled for your business.", 403)
            return view(*args, **kwargs)

        return wrapper

    return decorator
