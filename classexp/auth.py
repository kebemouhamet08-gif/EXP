"""Authentification locale, sessions et permissions."""

from __future__ import annotations

import re
import secrets
import sqlite3
from functools import wraps

from flask import Blueprint, g, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db


bp = Blueprint("auth", __name__, url_prefix="/api/auth")
ALLOWED_ROLES = {"STUDENT", "TEACHER"}
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def api_error(code: str, message: str, status: int):
    return jsonify(error=code, message=message), status


def csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def valid_csrf_token() -> bool:
    supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    return bool(expected and secrets.compare_digest(expected, supplied))


@bp.before_app_request
def load_logged_in_user() -> None:
    user_id = session.get("user_id")
    g.user = None
    if user_id is not None:
        g.user = get_db().execute(
            "SELECT id, nom, email, role, account_status FROM utilisateurs WHERE id = ?",
            (user_id,),
        ).fetchone()
        if g.user is None or g.user["account_status"] != "ACTIVE":
            session.clear()


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.user is None:
            if request.path.startswith("/api/"):
                return api_error("authentication_required", "Connexion requise.", 401)
            return redirect(url_for("pages.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped_view


def role_required(role: str):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped_view(*args, **kwargs):
            if g.user["role"] != role:
                if request.path.startswith("/api/"):
                    return api_error("forbidden", "Accès interdit pour ce rôle.", 403)
                return "Accès interdit.", 403
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


def credentials_from_request() -> dict:
    payload = request.get_json(silent=True) or request.form
    return {
        "name": str(payload.get("name") or payload.get("user_name") or "").strip(),
        "email": str(payload.get("email") or payload.get("user_mail") or "").strip().lower(),
        "password": str(payload.get("password") or payload.get("user_passwd") or ""),
        "role": str(payload.get("role") or "").strip().upper(),
    }


@bp.get("/csrf")
def get_csrf():
    return jsonify(csrf_token=csrf_token())


@bp.post("/register")
def register():
    if not valid_csrf_token():
        return api_error("invalid_csrf", "Jeton CSRF invalide ou absent.", 400)

    values = credentials_from_request()
    errors = {}
    if len(values["name"]) < 2:
        errors["name"] = "Le nom doit contenir au moins 2 caractères."
    if not EMAIL_PATTERN.fullmatch(values["email"]):
        errors["email"] = "Adresse e-mail invalide."
    if len(values["password"]) < 10:
        errors["password"] = "Le mot de passe doit contenir au moins 10 caractères."
    if values["role"] not in ALLOWED_ROLES:
        errors["role"] = "Le rôle doit être STUDENT ou TEACHER."
    if errors:
        return jsonify(error="validation_error", message="Données invalides.", fields=errors), 400

    try:
        cursor = get_db().execute(
            "INSERT INTO utilisateurs (nom, email, mot_de_passe_hash, role) VALUES (?, ?, ?, ?)",
            (
                values["name"],
                values["email"],
                generate_password_hash(values["password"], method="scrypt"),
                values["role"],
            ),
        )
        get_db().commit()
    except sqlite3.IntegrityError:
        return api_error("email_conflict", "Un compte utilise déjà cette adresse e-mail.", 409)

    return jsonify(id=cursor.lastrowid, name=values["name"], email=values["email"], role=values["role"]), 201


@bp.post("/login")
def login():
    if not valid_csrf_token():
        return api_error("invalid_csrf", "Jeton CSRF invalide ou absent.", 400)

    values = credentials_from_request()
    user = get_db().execute(
        "SELECT id, nom, email, mot_de_passe_hash, role, account_status "
        "FROM utilisateurs WHERE email = ?",
        (values["email"],),
    ).fetchone()
    if (
        user is None
        or user["account_status"] != "ACTIVE"
        or not check_password_hash(user["mot_de_passe_hash"], values["password"])
    ):
        return api_error("invalid_credentials", "E-mail ou mot de passe incorrect.", 401)

    session.clear()
    session["user_id"] = user["id"]
    csrf_token()
    return jsonify(id=user["id"], name=user["nom"], email=user["email"], role=user["role"])


@bp.post("/logout")
@login_required
def logout():
    if not valid_csrf_token():
        return api_error("invalid_csrf", "Jeton CSRF invalide ou absent.", 400)
    session.clear()
    return "", 204


@bp.get("/me")
@login_required
def me():
    return jsonify(id=g.user["id"], name=g.user["nom"], email=g.user["email"], role=g.user["role"])
