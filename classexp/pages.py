"""Routes HTML publiques de la première phase."""

from flask import Blueprint, g, redirect, render_template, request, url_for

from .auth import role_required


bp = Blueprint("pages", __name__)


@bp.get("/")
def home():
    return render_template("home.html")


@bp.route("/connexion", methods=("GET", "POST"))
def login():
    if g.user is not None:
        endpoint = "pages.student_dashboard" if g.user["role"] == "STUDENT" else "pages.teacher_dashboard"
        return redirect(url_for(endpoint))
    if request.method == "POST":
        return "Utilisez l’API d’authentification.", 400
    return render_template("login.html")


@bp.get("/eleve")
@role_required("STUDENT")
def student_dashboard():
    return render_template("dashboard.html", audience="élève")


@bp.get("/professeur")
@role_required("TEACHER")
def teacher_dashboard():
    return render_template("dashboard.html", audience="professeur")
