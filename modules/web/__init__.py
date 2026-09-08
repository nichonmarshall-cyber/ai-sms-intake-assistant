"""Dashboard web blueprints: auth, admin, and client APIs, plus the SPA catch-all.

register_blueprints() is called once from app.py, after every Twilio/system
route (/sms, /voice/missed-call, /health, /reset) is already registered. The
SPA blueprint is added last on purpose -- its catch-all route must never be
able to shadow those paths or /api/*.
"""

from __future__ import annotations

from flask import Flask

from modules.web.auth_routes import auth_bp
from modules.web.admin_routes import admin_bp
from modules.web.client_routes import client_bp
from modules.web.spa import spa_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(client_bp)
    app.register_blueprint(spa_bp)
