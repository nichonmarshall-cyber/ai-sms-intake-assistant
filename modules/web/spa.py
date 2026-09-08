"""Serves the compiled React bundle from the same origin as the API.

The dashboard is built by Vite into ``static/dist``, which is NOT committed and
is NOT built by Render during Phase 1a. When that directory is absent -- which
is exactly the state of the current Render deployment -- these routes return a
controlled 503. The Twilio and health routes are registered separately in
app.py and are entirely unaffected.
"""

from __future__ import annotations

import os

from flask import Blueprint, jsonify, send_from_directory

spa_bp = Blueprint("spa", __name__)

DIST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "dist")
INDEX_FILE = os.path.join(DIST_DIR, "index.html")

# API prefixes must never be swallowed by the catch-all.
RESERVED_PREFIXES = ("api/", "sms", "voice/", "health", "reset")


def dashboard_available() -> bool:
    return os.path.isfile(INDEX_FILE)


def _unavailable():
    return jsonify(
        {
            "error": "Dashboard bundle is not built in this environment.",
            "detail": "Run `npm run build` in frontend/ to produce static/dist.",
        }
    ), 503


@spa_bp.get("/assets/<path:filename>")
def spa_assets(filename: str):
    if not dashboard_available():
        return _unavailable()
    return send_from_directory(os.path.join(DIST_DIR, "assets"), filename)


@spa_bp.get("/")
@spa_bp.get("/<path:path>")
def spa_index(path: str = ""):
    if path.startswith(RESERVED_PREFIXES):
        return jsonify({"error": "Not found."}), 404
    if not dashboard_available():
        return _unavailable()
    return send_from_directory(DIST_DIR, "index.html")
