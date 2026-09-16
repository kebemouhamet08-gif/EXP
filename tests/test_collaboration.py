import io
from datetime import datetime, timedelta

import app as application_module


def csrf(client, path="/mon-compte"):
    with client.session_transaction() as session:
        session.setdefault("_csrf_token", "test-csrf-token")
        return session["_csrf_token"]


def register(client, email, role="ELEVE", name="Test"):
    assert client.post("/inscription", data={"nom": name, "email": email, "mot_de_passe": "motdepasse123", "role": role}).status_code == 302
    assert client.post("/connexion", data={"email": email, "mot_de_passe": "motdepasse123"}).status_code == 302


def create_class(client, name="GLSI 1"):
    client.post("/professeur/classe/nouvelle", data={"nom": name})
    with application_module.app.app_context():
        return application_module.get_db().execute("SELECT id,code FROM classes ORDER BY id DESC LIMIT 1").fetchone()


def test_multi_teacher_owner_transfer_and_removal(professor, app):
    owner=professor["client"]; classe=create_class(owner)
    second=app.test_client(); register(second,"second@example.com","PROFESSEUR","Prof B")
    token=csrf(owner)
    assert owner.post(f"/classe/{classe['id']}/enseignants/ajouter",data={"_csrf_token":token,"email":"second@example.com"}).status_code==302
    with app.app_context():
        db=application_module.get_db(); second_id=db.execute("SELECT id FROM utilisateurs WHERE email='second@example.com'").fetchone()[0]
        assert db.execute("SELECT role FROM classe_professeurs WHERE classe_id=? AND professeur_id=?",(classe["id"],second_id)).fetchone()[0]=="PROFESSEUR"
    assert second.get("/professeur").status_code==200
    assert second.post(f"/classe/{classe['id']}/enseignants/{professor.get('id', 0)}/retirer",data={"_csrf_token":csrf(second)}).status_code==403
    assert owner.post(f"/classe/{classe['id']}/propriete/{second_id}",data={"_csrf_token":token}).status_code==302
    with app.app_context():
        assert application_module.get_db().execute("SELECT role FROM classe_professeurs WHERE classe_id=? AND professeur_id=?",(classe["id"],second_id)).fetchone()[0]=="OWNER"


def test_student_removal_responsable_and_idor(professor, student, app):
    classe=create_class(professor["client"]); student["client"].post("/eleve/classe/rejoindre",data={"code":classe["code"]})
    with app.app_context(): sid=application_module.get_db().execute("SELECT id FROM utilisateurs WHERE email=?",(student["email"],)).fetchone()[0]
    token=csrf(professor["client"])
    assert student["client"].post(f"/classe/{classe['id']}/responsables/{sid}",data={"_csrf_token":csrf(student["client"]),"enabled":"1"}).status_code==403
    assert professor["client"].post(f"/classe/{classe['id']}/responsables/{sid}",data={"_csrf_token":token,"enabled":"1"}).status_code==302
    assert student["client"].get(f"/classe/{classe['id']}/membres").status_code==200
    assert professor["client"].post(f"/classe/{classe['id']}/eleves/{sid}/retirer",data={"_csrf_token":token}).status_code==302
    assert student["client"].get(f"/classe/{classe['id']}/membres").status_code==403
    with app.app_context(): assert application_module.get_db().execute("SELECT statut FROM classe_eleves WHERE classe_id=? AND eleve_id=?",(classe["id"],sid)).fetchone()[0]=="REMOVED"


def test_chat_participants_and_removed_member_cannot_send(professor, student, app):
    classe=create_class(professor["client"]); student["client"].post("/eleve/classe/rejoindre",data={"code":classe["code"]})
    with app.app_context():
        db=application_module.get_db(); sid=db.execute("SELECT id FROM utilisateurs WHERE email=?",(student["email"],)).fetchone()[0]; pid=db.execute("SELECT id FROM utilisateurs WHERE email=?",(professor["email"],)).fetchone()[0]
        db.execute("UPDATE class_settings SET chat_enabled=TRUE,students_can_start=TRUE WHERE classe_id=?",(classe["id"],)); db.commit()
    response=student["client"].post(f"/classe/{classe['id']}/messages/nouveau/{pid}",data={"_csrf_token":csrf(student["client"] )})
    assert response.status_code==302; conversation_id=int(response.location.rsplit("/",1)[1])
    stranger=app.test_client(); register(stranger,"stranger@example.com")
    assert stranger.get(f"/messages/{conversation_id}").status_code==403
    assert student["client"].post(f"/messages/{conversation_id}",data={"_csrf_token":csrf(student["client"]),"contenu":"Bonjour"}).status_code==302
    professor["client"].post(f"/classe/{classe['id']}/eleves/{sid}/retirer",data={"_csrf_token":csrf(professor["client"])})
    assert student["client"].post(f"/messages/{conversation_id}",data={"_csrf_token":csrf(student["client"]),"contenu":"Interdit"}).status_code==403


def test_correction_after_submission_and_cross_class_denied(professor, student, app):
    classe=create_class(professor["client"]); student["client"].post("/eleve/classe/rejoindre",data={"code":classe["code"]})
    with app.app_context():
        db=application_module.get_db(); sid=db.execute("SELECT id FROM utilisateurs WHERE email=?",(student["email"],)).fetchone()[0]
        aid=db.execute("INSERT INTO devoirs (titre,professeur_id,classe_id,date_ouverture,duree,correction_visibility) VALUES ('Test',1,?,?,3600,'AFTER_SUBMISSION') RETURNING id",(classe["id"],datetime.now().isoformat())).fetchone()[0]
        db.commit()
    response=professor["client"].post(f"/devoir/{aid}/correction",data={"_csrf_token":csrf(professor["client"]),"visibility":"AFTER_SUBMISSION","correction":(io.BytesIO(b"%PDF-test"),"correction.pdf")},content_type="multipart/form-data")
    assert response.status_code==302
    assert student["client"].get(f"/corrections/{aid}").status_code==403
    with app.app_context():
        db=application_module.get_db(); db.execute("INSERT INTO sessions_examen (eleve_id,devoir_id,heure_debut,heure_fin,statut) VALUES (?,?,?,?,'TERMINE')",(sid,aid,datetime.now().isoformat(),datetime.now().isoformat())); db.commit()
    download=student["client"].get(f"/corrections/{aid}"); assert download.status_code==200; download.close()


def test_admin_cli_cms_xss_and_maintenance_health(client, app):
    register(client,"admin@example.com","PROFESSEUR","Admin")
    runner=app.test_cli_runner(); assert runner.invoke(args=["make-admin","admin@example.com"]).exit_code==0
    client.get("/deconnexion"); client.post("/connexion",data={"email":"admin@example.com","mot_de_passe":"motdepasse123"})
    token=csrf(client); assert client.get("/admin").status_code==200
    response=client.post("/admin/contenu",data={"_csrf_token":token,"key":"home.hero","title":"<script>alert(1)</script>","content":"Bienvenue","enabled":"1","link_url":"javascript:alert(1)"})
    assert response.status_code==302
    with app.app_context():
        row=application_module.get_db().execute("SELECT title,link_url FROM site_content WHERE key='home.hero'").fetchone(); assert row["link_url"] is None
    assert client.post("/admin/maintenance",data={"_csrf_token":token,"enabled":"1","message":"Pause"}).status_code==302
    anonymous=app.test_client(); assert anonymous.get("/").status_code==503; assert anonymous.get("/health").status_code==200
    assert client.get("/admin").status_code==200


def test_new_destructive_routes_require_csrf(professor):
    classe=create_class(professor["client"])
    assert professor["client"].post(f"/classe/{classe['id']}/enseignants/ajouter",data={"email":"x@example.com"}).status_code==400
