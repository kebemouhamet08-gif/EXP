"""Fabrique d'application Flask de ClasseXP."""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request

from . import db


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    """Crée et configure une instance isolée de l'application."""
    app = Flask(
        __name__,
        instance_relative_config=True,
        static_folder="../static",
        template_folder="../templates",
    )
    app.config.from_mapping(
        DATABASE=str(Path(app.instance_path) / "classexp.sqlite"),
        SECRET_KEY=os.environ.get("CLASSEXP_SECRET_KEY") or secrets.token_hex(32),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("CLASSEXP_HTTPS", "0") == "1",
    )

    if test_config is not None:
        app.config.from_mapping(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    db.init_app(app)

    from .auth import bp as auth_bp
    from .pages import bp as pages_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(pages_bp)
    register_error_handlers(app)
    return app


def register_error_handlers(app: Flask) -> None:
    """Retourne du JSON pour l'API et les pages Flask ailleurs."""

    @app.errorhandler(404)
    def not_found(error):
        if request.path.startswith("/api/"):
            return jsonify(error="not_found", message="Ressource introuvable."), 404
        return error

    @app.errorhandler(405)
    def method_not_allowed(error):
        if request.path.startswith("/api/"):
            return jsonify(error="method_not_allowed", message="Méthode non autorisée."), 405
        return error
