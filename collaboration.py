"""Collaborative classroom and editorial administration routes.

The module is deliberately additive: legacy columns remain readable while all new
authorisation goes through permissions.py.
"""
from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.utils import secure_filename

from database import get_db
from permissions import (
    can_manage_assignment, can_manage_class, can_manage_members, can_view_members,
    is_admin, is_class_owner, is_class_responsable, is_class_student,
    is_class_teacher, is_conversation_participant,
)
from storage import StorageError, build_storage

bp = Blueprint("collaboration", __name__)
VISIBILITY = {"NEVER", "AFTER_END", "AFTER_SUBMISSION", "AT_DATE", "NOW"}
COLORS = {"indigo", "blue", "green", "violet", "orange"}
BANNER_TYPES = {"INFO", "SUCCESS", "WARNING", "IMPORTANT"}
IMAGE_TYPES = {"image/png": ("png", b"\x89PNG\r\n\x1a\n"), "image/jpeg": ("jpg", b"\xff\xd8\xff")}


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def csrf_ok():
    supplied = request.form.get("_csrf_token", "") or request.headers.get("X-CSRF-Token", "")
    expected = session.get("_csrf_token", "")
    return bool(expected and secrets.compare_digest(supplied, expected))


def csrf_protected(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not csrf_ok():
            abort(400, "Jeton CSRF invalide.")
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not is_admin(current_user):
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def audit(action, entity_type, entity_id=None, metadata=None, actor_id=None):
    get_db().execute(
        "INSERT INTO audit_logs (actor_user_id, action, entity_type, entity_id, metadata_json) VALUES (?, ?, ?, ?, ?)",
        (actor_id if actor_id is not None else current_user.id, action, entity_type,
         str(entity_id) if entity_id is not None else None, json.dumps(metadata or {}, ensure_ascii=False)),
    )


def notify(user_id, kind, title, message, url=None):
    get_db().execute(
        "INSERT INTO notifications (utilisateur_id, type, titre, message, url) VALUES (?, ?, ?, ?, ?)",
        (user_id, kind, title, message, url),
    )


def _class_or_404(classe_id):
    row = get_db().execute("SELECT id, nom, code FROM classes WHERE id=?", (classe_id,)).fetchone()
    if row is None:
        abort(404)
    return row


@bp.get("/classe/<int:classe_id>/membres")
@login_required
def members(classe_id):
    db = get_db(); classe = _class_or_404(classe_id)
    if not can_view_members(db, current_user.id, classe_id):
        abort(403)
    teachers = db.execute(
        """SELECT u.id,u.nom,u.email,cp.role,cp.date_ajout FROM classe_professeurs cp
           JOIN utilisateurs u ON u.id=cp.professeur_id WHERE cp.classe_id=? ORDER BY cp.role DESC,u.nom""", (classe_id,)
    ).fetchall()
    students = db.execute(
        """SELECT u.id,u.nom,u.email,ce.role,ce.can_view_members,ce.can_send_announcements,
                  ce.can_contact_students,ce.can_contact_teachers
           FROM classe_eleves ce JOIN utilisateurs u ON u.id=ce.eleve_id
           WHERE ce.classe_id=? AND ce.statut='ACTIVE' ORDER BY ce.role DESC,u.nom""", (classe_id,)
    ).fetchall()
    settings = db.execute("SELECT * FROM class_settings WHERE classe_id=?", (classe_id,)).fetchone()
    return render_template("collaboration.html", view="members", classe=classe, teachers=teachers,
                           students=students, settings=settings,
                           is_teacher=is_class_teacher(db, current_user.id, classe_id),
                           is_owner=is_class_owner(db, current_user.id, classe_id))


@bp.post("/classe/<int:classe_id>/enseignants/ajouter")
@login_required
@csrf_protected
def add_teacher(classe_id):
    db = get_db(); classe = _class_or_404(classe_id)
    if not can_manage_class(db, current_user.id, classe_id): abort(403)
    email = request.form.get("email", "").strip().lower()
    user = db.execute("SELECT id,role FROM utilisateurs WHERE email=?", (email,)).fetchone()
    if user is None or user["role"] not in {"PROFESSEUR", "ADMIN"}:
        flash("Le compte professeur ou administrateur est introuvable.", "error")
        return redirect(url_for("collaboration.members", classe_id=classe_id))
    try:
        db.execute("INSERT INTO classe_professeurs (classe_id,professeur_id,role,ajoute_par) VALUES (?,?,'PROFESSEUR',?)",
                   (classe_id, user["id"], current_user.id))
        notify(user["id"], "TEACHER_ADDED", "Nouvelle classe", f"Vous avez été ajouté comme professeur de la classe {classe['nom']}.", url_for("collaboration.members", classe_id=classe_id))
        audit("TEACHER_ADDED", "class", classe_id, {"teacher_id": user["id"]}); db.commit()
        flash("Professeur ajouté.", "success")
    except IntegrityError:
        db.rollback(); flash("Ce professeur appartient déjà à la classe.", "warning")
    return redirect(url_for("collaboration.members", classe_id=classe_id))


@bp.post("/classe/<int:classe_id>/enseignants/<int:user_id>/retirer")
@login_required
@csrf_protected
def remove_teacher(classe_id, user_id):
    db=get_db(); classe=_class_or_404(classe_id)
    if not can_manage_class(db,current_user.id,classe_id): abort(403)
    membership=db.execute("SELECT role FROM classe_professeurs WHERE classe_id=? AND professeur_id=?",(classe_id,user_id)).fetchone()
    if membership is None: abort(404)
    if membership["role"] == "OWNER": abort(409, "Le propriétaire doit d'abord transférer la propriété.")
    db.execute("DELETE FROM classe_professeurs WHERE classe_id=? AND professeur_id=?",(classe_id,user_id))
    notify(user_id,"TEACHER_REMOVED","Classe",f"Vous avez été retiré de la classe {classe['nom']}.")
    audit("TEACHER_REMOVED","class",classe_id,{"teacher_id":user_id}); db.commit(); flash("Professeur retiré.","success")
    return redirect(url_for("collaboration.members",classe_id=classe_id))


@bp.post("/classe/<int:classe_id>/propriete/<int:user_id>")
@login_required
@csrf_protected
def transfer_owner(classe_id,user_id):
    db=get_db(); classe=_class_or_404(classe_id)
    if not is_class_owner(db,current_user.id,classe_id): abort(403)
    target=db.execute("SELECT 1 FROM classe_professeurs WHERE classe_id=? AND professeur_id=?",(classe_id,user_id)).fetchone()
    if target is None or user_id == current_user.id: abort(400)
    try:
        db.execute("UPDATE classe_professeurs SET role='PROFESSEUR' WHERE classe_id=? AND professeur_id=? AND role='OWNER'",(classe_id,current_user.id))
        db.execute("UPDATE classe_professeurs SET role='OWNER' WHERE classe_id=? AND professeur_id=?",(classe_id,user_id))
        # Legacy compatibility remains synchronized during the transition period.
        db.execute("UPDATE classes SET professeur_id=? WHERE id=?",(user_id,classe_id))
        notify(user_id,"OWNER_TRANSFERRED","Propriété transférée",f"Vous êtes propriétaire de la classe {classe['nom']}.")
        audit("OWNER_TRANSFERRED","class",classe_id,{"old_owner_id":current_user.id,"new_owner_id":user_id}); db.commit()
    except SQLAlchemyError:
        db.rollback(); raise
    flash("Propriété transférée.","success")
    return redirect(url_for("collaboration.members",classe_id=classe_id))


@bp.post("/classe/<int:classe_id>/eleves/<int:user_id>/retirer")
@login_required
@csrf_protected
def remove_student(classe_id,user_id):
    db=get_db(); classe=_class_or_404(classe_id)
    if not can_manage_members(db,current_user.id,classe_id): abort(403)
    result=db.execute("UPDATE classe_eleves SET statut='REMOVED',role='ELEVE',removed_at=?,removed_by=? WHERE classe_id=? AND eleve_id=? AND statut='ACTIVE'",
                      (now().isoformat(timespec="seconds"),current_user.id,classe_id,user_id))
    if not result.rowcount: abort(404)
    notify(user_id,"STUDENT_REMOVED","Classe",f"Vous avez été retiré de la classe {classe['nom']}.")
    audit("STUDENT_REMOVED","class",classe_id,{"student_id":user_id}); db.commit(); flash("Élève retiré de la classe.","success")
    return redirect(url_for("collaboration.members",classe_id=classe_id))


@bp.post("/classe/<int:classe_id>/responsables/<int:user_id>")
@login_required
@csrf_protected
def set_responsable(classe_id,user_id):
    db=get_db(); classe=_class_or_404(classe_id)
    if not can_manage_members(db,current_user.id,classe_id): abort(403)
    enabled=request.form.get("enabled","1") == "1"; role="RESPONSABLE" if enabled else "ELEVE"
    result=db.execute("UPDATE classe_eleves SET role=? WHERE classe_id=? AND eleve_id=? AND statut='ACTIVE'",(role,classe_id,user_id))
    if not result.rowcount: abort(404)
    event="RESPONSABLE_ADDED" if enabled else "RESPONSABLE_REMOVED"
    notify(user_id,event,"Rôle de classe",f"Votre rôle de responsable dans {classe['nom']} a été {'activé' if enabled else 'retiré'}.")
    audit(event,"class",classe_id,{"student_id":user_id}); db.commit(); flash("Rôle mis à jour.","success")
    return redirect(url_for("collaboration.members",classe_id=classe_id))


@bp.post("/classe/<int:classe_id>/responsables/<int:user_id>/permissions")
@login_required
@csrf_protected
def responsable_permissions(classe_id,user_id):
    db=get_db(); _class_or_404(classe_id)
    if not can_manage_members(db,current_user.id,classe_id): abort(403)
    values=tuple(request.form.get(name)=="1" for name in ("can_view_members","can_send_announcements","can_contact_students","can_contact_teachers"))
    result=db.execute("""UPDATE classe_eleves SET can_view_members=?,can_send_announcements=?,can_contact_students=?,can_contact_teachers=?
                         WHERE classe_id=? AND eleve_id=? AND statut='ACTIVE' AND role='RESPONSABLE'""",values+(classe_id,user_id))
    if not result.rowcount: abort(404)
    audit("RESPONSABLE_PERMISSIONS_UPDATED","class",classe_id,{"student_id":user_id}); db.commit(); flash("Permissions mises à jour.","success")
    return redirect(url_for("collaboration.members",classe_id=classe_id))


@bp.post("/classe/<int:classe_id>/chat/parametres")
@login_required
@csrf_protected
def chat_settings(classe_id):
    db=get_db(); _class_or_404(classe_id)
    if not can_manage_class(db,current_user.id,classe_id): abort(403)
    vals=tuple(request.form.get(x)=="1" for x in ("chat_enabled","students_can_start","responsables_can_contact_students"))
    db.execute("UPDATE class_settings SET chat_enabled=?,students_can_start=?,responsables_can_contact_students=? WHERE classe_id=?",vals+(classe_id,))
    audit("CHAT_SETTINGS_UPDATED","class",classe_id); db.commit(); flash("Paramètres du chat enregistrés.","success")
    return redirect(url_for("collaboration.members",classe_id=classe_id))


def _progress_rows(classe_id, student_id=None):
    where=" AND u.id=?" if student_id is not None else ""; params=(classe_id,student_id) if student_id is not None else (classe_id,)
    return get_db().execute("""SELECT u.id,u.nom,
      COUNT(d.id) AS assigned,
      SUM(CASE WHEN s.statut='TERMINE' THEN 1 ELSE 0 END) AS submitted,
      SUM(CASE WHEN s.statut='TERMINE' AND s.heure_fin <= d.date_ouverture + d.duree * INTERVAL '1 second' THEN 1 ELSE 0 END) AS on_time,
      SUM(CASE WHEN s.statut='TERMINE' AND s.heure_fin > d.date_ouverture + d.duree * INTERVAL '1 second' THEN 1 ELSE 0 END) AS late,
      SUM(CASE WHEN s.id IS NULL OR s.statut!='TERMINE' THEN 1 ELSE 0 END) AS missing,
      AVG(s.note) AS average, COUNT(s.note) AS grade_count
      FROM classe_eleves ce JOIN utilisateurs u ON u.id=ce.eleve_id
      LEFT JOIN devoirs d ON d.classe_id=ce.classe_id
      LEFT JOIN sessions_examen s ON s.devoir_id=d.id AND s.eleve_id=u.id
      WHERE ce.classe_id=? AND ce.statut='ACTIVE'"""+where+" GROUP BY u.id,u.nom ORDER BY u.nom",params).fetchall()


def _progress_rows_portable(classe_id, student_id=None):
    # Deadline arithmetic differs by backend, so calculate timing in Python while
    # retaining one bounded aggregate query for counts and grades.
    db=get_db(); extra=" AND u.id=?" if student_id is not None else ""; params=(classe_id,student_id) if student_id else (classe_id,)
    rows=db.execute("""SELECT u.id,u.nom,d.id AS devoir_id,d.date_ouverture,d.duree,s.statut,s.heure_fin,s.note
      FROM classe_eleves ce JOIN utilisateurs u ON u.id=ce.eleve_id LEFT JOIN devoirs d ON d.classe_id=ce.classe_id
      LEFT JOIN sessions_examen s ON s.devoir_id=d.id AND s.eleve_id=u.id
      WHERE ce.classe_id=? AND ce.statut='ACTIVE'"""+extra+" ORDER BY u.nom,d.date_ouverture",params).fetchall()
    result={}
    for row in rows:
        item=result.setdefault(row["id"],{"id":row["id"],"nom":row["nom"],"assigned":0,"submitted":0,"on_time":0,"late":0,"missing":0,"grades":[]})
        if row["devoir_id"] is None: continue
        item["assigned"]+=1
        if row["statut"]=="TERMINE":
            item["submitted"]+=1
            try:
                opening=datetime.fromisoformat(row["date_ouverture"]); submitted=datetime.fromisoformat(row["heure_fin"])
                item["on_time" if submitted <= opening+timedelta(seconds=row["duree"]) else "late"]+=1
            except (TypeError,ValueError): pass
        else: item["missing"]+=1
        if row["note"] is not None: item["grades"].append(float(row["note"]))
    for item in result.values():
        item["grade_count"]=len(item["grades"]); item["average"]=round(sum(item["grades"])/len(item["grades"]),1) if item["grades"] else None
        item["recent_grades"]=item["grades"][-5:]; item["trend"]=(round(item["grades"][-1]-item["grades"][-2],1) if len(item["grades"])>=2 else None)
    return list(result.values())


@bp.get("/classe/<int:classe_id>/progression")
@login_required
def class_progress(classe_id):
    db=get_db(); classe=_class_or_404(classe_id)
    if not is_class_teacher(db,current_user.id,classe_id): abort(403)
    return render_template("collaboration.html",view="progress",classe=classe,progress=_progress_rows_portable(classe_id))


@bp.get("/classe/<int:classe_id>/ma-progression")
@login_required
def my_progress(classe_id):
    db=get_db(); classe=_class_or_404(classe_id)
    if not is_class_student(db,current_user.id,classe_id): abort(403)
    return render_template("collaboration.html",view="progress",classe=classe,progress=_progress_rows_portable(classe_id,current_user.id),mine=True)


def correction_allowed(assignment, user_id):
    db=get_db()
    if is_class_teacher(db,user_id,assignment["classe_id"]): return True
    if not is_class_student(db,user_id,assignment["classe_id"]): return False
    mode=assignment["correction_visibility"]
    if mode=="NOW": return True
    if mode=="AT_DATE":
        return bool(assignment["correction_visible_at"] and now() >= datetime.fromisoformat(assignment["correction_visible_at"]))
    session_row=db.execute("SELECT statut,heure_fin FROM sessions_examen WHERE devoir_id=? AND eleve_id=?",(assignment["id"],user_id)).fetchone()
    if mode=="AFTER_SUBMISSION": return bool(session_row and session_row["statut"]=="TERMINE")
    if mode=="AFTER_END":
        opening=datetime.fromisoformat(assignment["date_ouverture"])
        return now() >= opening+timedelta(seconds=assignment["duree"])
    return False


@bp.post("/devoir/<int:devoir_id>/correction")
@login_required
@csrf_protected
def save_correction(devoir_id):
    db=get_db(); assignment=db.execute("SELECT * FROM devoirs WHERE id=?",(devoir_id,)).fetchone()
    if assignment is None: abort(404)
    if not can_manage_assignment(db,current_user.id,assignment["classe_id"]): abort(403)
    visibility=request.form.get("visibility","NEVER")
    if visibility not in VISIBILITY: abort(400)
    visible_at=request.form.get("visible_at") or None
    if visibility=="AT_DATE":
        try: datetime.fromisoformat(visible_at)
        except (TypeError,ValueError): abort(400)
    upload=request.files.get("correction"); key=assignment["correction_pdf"]
    if upload and upload.filename:
        ext=secure_filename(upload.filename).rsplit(".",1)[-1].lower()
        if ext not in {"pdf","jpg","png","docx"}: abort(400)
        key=f"corrections/devoir-{devoir_id}/{uuid.uuid4().hex}.{ext}"
        upload.stream.seek(0,2); size=upload.stream.tell(); upload.stream.seek(0)
        if not 0<size<=current_app.config["MAX_CONTENT_LENGTH"]: abort(400)
        build_storage(current_app.config).put(key,upload.stream,content_type=upload.mimetype)
        db.execute("INSERT INTO fichiers (storage_key,original_filename,content_type,size,kind,owner_user_id,devoir_id) VALUES (?,?,?,?,'CORRECTION',?,?)",
                   (key,secure_filename(upload.filename),upload.mimetype or "application/octet-stream",size,current_user.id,devoir_id))
    db.execute("UPDATE devoirs SET correction_pdf=?,correction_text=?,correction_visibility=?,correction_visible_at=? WHERE id=?",
               (key,request.form.get("correction_text","").strip() or None,visibility,visible_at,devoir_id))
    audit("CORRECTION_PUBLISHED","assignment",devoir_id,{"visibility":visibility}); db.commit(); flash("Correction publiée.","success")
    return redirect(url_for("voir_copies",devoir_id=devoir_id))


@bp.get("/corrections/<int:devoir_id>")
@login_required
def get_correction(devoir_id):
    assignment=get_db().execute("SELECT * FROM devoirs WHERE id=?",(devoir_id,)).fetchone()
    if assignment is None: abort(404)
    if not correction_allowed(assignment,current_user.id): abort(403)
    if not assignment["correction_pdf"]: abort(404)
    metadata=get_db().execute("SELECT original_filename,content_type FROM fichiers WHERE storage_key=?",(assignment["correction_pdf"],)).fetchone()
    try:
        return build_storage(current_app.config).response(assignment["correction_pdf"],download_name=metadata["original_filename"] if metadata else "correction",content_type=metadata["content_type"] if metadata else None)
    except FileNotFoundError: abort(404)


def _chat_enabled(db,classe_id):
    row=db.execute("SELECT chat_enabled,students_can_start,responsables_can_contact_students FROM class_settings WHERE classe_id=?",(classe_id,)).fetchone()
    return row


@bp.get("/messages")
@login_required
def message_list():
    rows=get_db().execute("""SELECT c.id,c.classe_id,cl.nom AS classe_nom,MAX(m.created_at) AS last_at
      FROM conversations c JOIN conversation_participants cp ON cp.conversation_id=c.id JOIN classes cl ON cl.id=c.classe_id
      LEFT JOIN messages m ON m.conversation_id=c.id WHERE cp.utilisateur_id=? GROUP BY c.id,c.classe_id,cl.nom ORDER BY last_at DESC LIMIT 50""",(current_user.id,)).fetchall()
    return render_template("collaboration.html",view="messages",conversations=rows)


@bp.post("/classe/<int:classe_id>/messages/nouveau/<int:user_id>")
@login_required
@csrf_protected
def new_conversation(classe_id,user_id):
    db=get_db(); _class_or_404(classe_id); settings=_chat_enabled(db,classe_id)
    if settings is None or not settings["chat_enabled"]: abort(403)
    me_teacher=is_class_teacher(db,current_user.id,classe_id); them_teacher=is_class_teacher(db,user_id,classe_id)
    me_student=is_class_student(db,current_user.id,classe_id); them_student=is_class_student(db,user_id,classe_id)
    allowed=(me_teacher and them_student) or (me_student and them_teacher and settings["students_can_start"])
    if not allowed: abort(403)
    existing=db.execute("""SELECT c.id FROM conversations c JOIN conversation_participants a ON a.conversation_id=c.id
      JOIN conversation_participants b ON b.conversation_id=c.id WHERE c.classe_id=? AND a.utilisateur_id=? AND b.utilisateur_id=?""",(classe_id,current_user.id,user_id)).fetchone()
    if existing: return redirect(url_for("collaboration.conversation",conversation_id=existing["id"]))
    row=db.execute("INSERT INTO conversations (classe_id,created_by) VALUES (?,?) RETURNING id",(classe_id,current_user.id)).fetchone()
    for participant in (current_user.id,user_id): db.execute("INSERT INTO conversation_participants (conversation_id,utilisateur_id) VALUES (?,?)",(row["id"],participant))
    db.commit(); return redirect(url_for("collaboration.conversation",conversation_id=row["id"]))


def _conversation_access(conversation_id):
    db=get_db(); row=db.execute("SELECT c.*,cs.chat_enabled FROM conversations c JOIN class_settings cs ON cs.classe_id=c.classe_id WHERE c.id=?",(conversation_id,)).fetchone()
    if row is None: abort(404)
    if not is_conversation_participant(db,current_user.id,conversation_id): abort(403)
    if not (is_class_teacher(db,current_user.id,row["classe_id"]) or is_class_student(db,current_user.id,row["classe_id"])): abort(403)
    return row


@bp.get("/messages/<int:conversation_id>")
@login_required
def conversation(conversation_id):
    convo=_conversation_access(conversation_id)
    rows=get_db().execute("""SELECT m.id,m.auteur_id,m.contenu,m.created_at,u.nom FROM messages m JOIN utilisateurs u ON u.id=m.auteur_id
      WHERE m.conversation_id=? ORDER BY m.created_at DESC LIMIT 100""",(conversation_id,)).fetchall()
    return render_template("collaboration.html",view="conversation",conversation=convo,messages=list(reversed(rows)))


@bp.post("/messages/<int:conversation_id>")
@login_required
@csrf_protected
def send_message(conversation_id):
    db=get_db(); convo=_conversation_access(conversation_id)
    if not convo["chat_enabled"]: abort(403)
    content=request.form.get("contenu","").strip()
    if not content or len(content)>4000: abort(400)
    db.execute("INSERT INTO messages (conversation_id,auteur_id,contenu) VALUES (?,?,?)",(conversation_id,current_user.id,content))
    recipients=db.execute("SELECT utilisateur_id FROM conversation_participants WHERE conversation_id=? AND utilisateur_id!=?",(conversation_id,current_user.id)).fetchall()
    for recipient in recipients: notify(recipient["utilisateur_id"],"NEW_MESSAGE","Nouveau message",f"Message de {current_user.nom}.",url_for("collaboration.conversation",conversation_id=conversation_id))
    db.commit(); flash("Message envoyé.","success"); return redirect(url_for("collaboration.conversation",conversation_id=conversation_id))


@bp.get("/notifications")
@login_required
def notification_list():
    rows=get_db().execute("SELECT * FROM notifications WHERE utilisateur_id=? ORDER BY created_at DESC LIMIT 100",(current_user.id,)).fetchall()
    return render_template("collaboration.html",view="notifications",notifications=rows)


def safe_link(value):
    value=(value or "").strip()
    if not value: return None
    parsed=urlsplit(value)
    return value if (not parsed.scheme and not parsed.netloc and value.startswith("/")) or parsed.scheme in {"http","https","mailto"} else None


def store_site_image(upload, folder):
    if not upload or not upload.filename or upload.mimetype not in IMAGE_TYPES:
        return None
    extension, signature = IMAGE_TYPES[upload.mimetype]
    upload.stream.seek(0); header = upload.stream.read(len(signature))
    upload.stream.seek(0, 2); size = upload.stream.tell(); upload.stream.seek(0)
    if header != signature or not 0 < size <= min(current_app.config["MAX_CONTENT_LENGTH"], 5 * 1024 * 1024):
        abort(400, "Image invalide.")
    key = f"site-content/{folder}/{uuid.uuid4().hex}.{extension}"
    build_storage(current_app.config).put(key, upload.stream, content_type=upload.mimetype)
    get_db().execute("INSERT INTO fichiers (storage_key,original_filename,content_type,size,kind,owner_user_id) VALUES (?,?,?,?,'SITE_IMAGE',?)",
                     (key, secure_filename(upload.filename), upload.mimetype, size, current_user.id))
    return key


@bp.get("/site-media/<path:key>")
def site_media(key):
    key = key.replace("\\", "/").lstrip("/")
    if ".." in key.split("/") or not key.startswith("site-content/"):
        abort(404)
    metadata = get_db().execute("SELECT original_filename,content_type FROM fichiers WHERE storage_key=? AND kind='SITE_IMAGE'",(key,)).fetchone()
    if metadata is None: abort(404)
    try:
        return build_storage(current_app.config).response(key,download_name=metadata["original_filename"],content_type=metadata["content_type"])
    except FileNotFoundError: abort(404)


@bp.get("/admin")
@admin_required
def admin_home():
    db=get_db()
    if db.execute("SELECT 1 FROM site_settings WHERE id=1").fetchone() is None:
        db.execute("INSERT INTO site_settings (id,public_name,primary_color) VALUES (1,'ClasseXP','indigo')")
        db.commit()
    return render_template("collaboration.html",view="admin",content=db.execute("SELECT * FROM site_content ORDER BY position,key").fetchall(),
      banners=db.execute("SELECT * FROM site_banners ORDER BY id DESC").fetchall(),settings=db.execute("SELECT * FROM site_settings WHERE id=1").fetchone())


@bp.post("/admin/contenu")
@admin_required
@csrf_protected
def admin_content():
    key=request.form.get("key","").strip().lower()
    if not key or len(key)>100 or not all(c.isalnum() or c in "._-" for c in key): abort(400)
    db=get_db(); existing=db.execute("SELECT id FROM site_content WHERE key=?",(key,)).fetchone()
    image_key=store_site_image(request.files.get("image"),"home")
    values=(request.form.get("title","").strip(),request.form.get("content","").strip(),safe_link(request.form.get("link_url")),request.form.get("enabled")=="1",request.form.get("position",type=int) or 0,current_user.id,now().isoformat(timespec="seconds"))
    if existing:
        db.execute("UPDATE site_content SET title=?,content=?,link_url=?,enabled=?,position=?,updated_by=?,updated_at=? WHERE key=?",values+(key,))
        if image_key: db.execute("UPDATE site_content SET image_object_key=? WHERE key=?",(image_key,key))
    else: db.execute("INSERT INTO site_content (title,content,link_url,enabled,position,updated_by,updated_at,key,image_object_key) VALUES (?,?,?,?,?,?,?,?,?)",values+(key,image_key))
    audit("CMS_UPDATED","site_content",key); db.commit(); flash("Contenu enregistré.","success"); return redirect(url_for("collaboration.admin_home"))


@bp.post("/admin/bannieres")
@admin_required
@csrf_protected
def admin_banner():
    kind=request.form.get("type","INFO")
    if kind not in BANNER_TYPES or not request.form.get("message","").strip(): abort(400)
    db=get_db(); row=db.execute("INSERT INTO site_banners (enabled,type,message,link,starts_at,ends_at,updated_by) VALUES (?,?,?,?,?,?,?) RETURNING id",
      (request.form.get("enabled")=="1",kind,request.form["message"].strip(),safe_link(request.form.get("link")),request.form.get("starts_at") or None,request.form.get("ends_at") or None,current_user.id)).fetchone()
    audit("BANNER_UPDATED","site_banner",row["id"]); db.commit(); flash("Bannière enregistrée.","success"); return redirect(url_for("collaboration.admin_home"))


@bp.post("/admin/apparence")
@admin_required
@csrf_protected
def admin_branding():
    color=request.form.get("primary_color","indigo")
    if color not in COLORS: abort(400)
    db=get_db(); logo=store_site_image(request.files.get("logo"),"branding"); favicon=store_site_image(request.files.get("favicon"),"branding"); home=store_site_image(request.files.get("home_image"),"branding")
    db.execute("UPDATE site_settings SET public_name=?,description=?,primary_color=?,updated_by=?,updated_at=? WHERE id=1",
      (request.form.get("public_name","").strip() or "ClasseXP",request.form.get("description","").strip(),color,current_user.id,now().isoformat(timespec="seconds")))
    if logo: db.execute("UPDATE site_settings SET logo_object_key=? WHERE id=1",(logo,))
    if favicon: db.execute("UPDATE site_settings SET favicon_object_key=? WHERE id=1",(favicon,))
    if home: db.execute("UPDATE site_settings SET home_image_object_key=? WHERE id=1",(home,))
    audit("BRANDING_UPDATED","site_settings",1); db.commit(); flash("Apparence enregistrée.","success"); return redirect(url_for("collaboration.admin_home"))


@bp.post("/admin/maintenance")
@admin_required
@csrf_protected
def admin_maintenance():
    enabled=request.form.get("enabled")=="1"; db=get_db()
    db.execute("UPDATE site_settings SET maintenance_enabled=?,maintenance_message=?,maintenance_starts_at=?,maintenance_ends_at=?,updated_by=?,updated_at=? WHERE id=1",
      (enabled,request.form.get("message","").strip(),request.form.get("starts_at") or None,request.form.get("ends_at") or None,current_user.id,now().isoformat(timespec="seconds")))
    audit("MAINTENANCE_UPDATED","site_settings",1,{"enabled":enabled}); db.commit(); flash("Maintenance mise à jour.","success"); return redirect(url_for("collaboration.admin_home"))


@bp.get("/admin/audit")
@admin_required
def admin_audit():
    page=max(1,request.args.get("page",1,type=int)); rows=get_db().execute("SELECT a.*,u.email FROM audit_logs a LEFT JOIN utilisateurs u ON u.id=a.actor_user_id ORDER BY a.created_at DESC LIMIT 100 OFFSET ?",((page-1)*100,)).fetchall()
    return render_template("collaboration.html",view="audit",logs=rows,page=page)
