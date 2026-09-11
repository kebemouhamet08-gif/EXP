import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, g, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder=None)
app.config['SECRET_KEY'] = os.environ.get('CLASSEXP_SECRET_KEY', 'dev-secret-change-me')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'uploads')
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'png', 'docx'}
DATABASE = os.path.join(app.root_path, 'database', 'classexp.db')


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql', mode='r', encoding='utf-8') as file:
            db.cursor().executescript(file.read())
        db.commit()


def ensure_db_initialized():
    with app.app_context():
        db = get_db()
        table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'utilisateurs'"
        ).fetchone()
        if table is None:
            with app.open_resource('schema.sql', mode='r', encoding='utf-8') as file:
                db.executescript(file.read())
            db.commit()


ensure_db_initialized()


@app.cli.command('init-db')
def init_db_command():
    """Efface les donnees existantes et cree les tables."""
    init_db()
    print('La base de donnees ClasseXP a ete initialisee avec succes.')


@app.route('/')
def accueil():
    return send_from_directory(app.root_path, 'index.html')


@app.route('/inscription', methods=['GET', 'POST'])
def inscription():
    if request.method == 'POST':
        nom = request.form.get('nom', '').strip()
        email = request.form.get('email', '').strip().lower()
        mot_de_passe = request.form.get('mot_de_passe', '')
        role = request.form.get('role', 'ELEVE')

        if not nom or not email or len(mot_de_passe) < 8:
            return render_template('auth.html', mode='inscription', error='Remplissez tous les champs. Le mot de passe doit contenir 8 caracteres minimum.')
        if role not in {'ELEVE', 'PROFESSEUR'}:
            return render_template('auth.html', mode='inscription', error='Role invalide.')

        try:
            db = get_db()
            db.execute(
                'INSERT INTO utilisateurs (nom, email, mot_de_passe_hash, role) VALUES (?, ?, ?, ?)',
                (nom, email, generate_password_hash(mot_de_passe), role),
            )
            db.commit()
        except sqlite3.IntegrityError:
            return render_template('auth.html', mode='inscription', error='Cette adresse email est deja utilisee.')
        return redirect(url_for('connexion'))

    return render_template('auth.html', mode='inscription')


@app.route('/connexion', methods=['GET', 'POST'])
def connexion():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        mot_de_passe = request.form.get('mot_de_passe', '')
        utilisateur = get_db().execute(
            'SELECT * FROM utilisateurs WHERE email = ?', (email,)
        ).fetchone()
        if utilisateur is None or not check_password_hash(utilisateur['mot_de_passe_hash'], mot_de_passe):
            return render_template('auth.html', mode='connexion', error='Email ou mot de passe incorrect.')

        session.clear()
        session['utilisateur_id'] = utilisateur['id']
        session['role'] = utilisateur['role']
        return redirect(url_for('dashboard'))

    return render_template('auth.html', mode='connexion')


@app.get('/deconnexion')
def deconnexion():
    session.clear()
    return redirect(url_for('connexion'))


def connexion_requise(route):
    @wraps(route)
    def route_protegee(*args, **kwargs):
        if 'utilisateur_id' not in session:
            return redirect(url_for('connexion'))
        return route(*args, **kwargs)
    return route_protegee


def role_requis(role):
    def decorateur(route):
        @wraps(route)
        @connexion_requise
        def route_protegee(*args, **kwargs):
            if session.get('role') != role:
                if session.get('role') == 'PROFESSEUR':
                    return redirect(url_for('dashboard_professeur'))
                if session.get('role') == 'ELEVE':
                    return redirect(url_for('dashboard_eleve'))
                session.clear()
                return redirect(url_for('connexion'))
            return route(*args, **kwargs)
        return route_protegee
    return decorateur


@app.get('/dashboard')
@connexion_requise
def dashboard():
    if session['role'] == 'PROFESSEUR':
        return redirect(url_for('dashboard_professeur'))
    return redirect(url_for('dashboard_eleve'))


@app.get('/eleve')
@role_requis('ELEVE')
def dashboard_eleve():
    utilisateur = get_db().execute(
        'SELECT nom, email FROM utilisateurs WHERE id = ?', (session['utilisateur_id'],)
    ).fetchone()
    devoirs = get_db().execute(
          '''SELECT d.*, c.nom AS classe_nom, s.note, s.commentaire,
                        EXISTS(SELECT 1 FROM sessions_examen sx WHERE sx.devoir_id = d.id AND sx.eleve_id = ?) AS commence
           FROM devoirs d
           JOIN classes c ON c.id = d.classe_id
           JOIN classe_eleves ce ON ce.classe_id = c.id
              LEFT JOIN sessions_examen s ON s.devoir_id = d.id AND s.eleve_id = ?
           WHERE ce.eleve_id = ?
           ORDER BY d.date_ouverture DESC''',
          (session['utilisateur_id'], session['utilisateur_id'], session['utilisateur_id']),
    ).fetchall()
    classes = get_db().execute(
        'SELECT c.nom, c.code FROM classes c JOIN classe_eleves ce ON ce.classe_id = c.id WHERE ce.eleve_id = ?',
        (session['utilisateur_id'],),
    ).fetchall()
    return render_template('dashboard.html', utilisateur=utilisateur, role='ELEVE', devoirs=devoirs, classes=classes)


@app.get('/professeur')
@role_requis('PROFESSEUR')
def dashboard_professeur():
    utilisateur = get_db().execute(
        'SELECT nom, email FROM utilisateurs WHERE id = ?', (session['utilisateur_id'],)
    ).fetchone()
    db = get_db()
    classes = db.execute(
        '''SELECT c.*, COUNT(ce.eleve_id) AS nombre_eleves
           FROM classes c LEFT JOIN classe_eleves ce ON ce.classe_id = c.id
           WHERE c.professeur_id = ? GROUP BY c.id ORDER BY c.nom''',
        (session['utilisateur_id'],),
    ).fetchall()
    devoirs = db.execute(
        '''SELECT d.*, c.nom AS classe_nom,
                  COUNT(s.id) AS copies
           FROM devoirs d JOIN classes c ON c.id = d.classe_id
           LEFT JOIN sessions_examen s ON s.devoir_id = d.id AND s.fichier_copie IS NOT NULL
           WHERE d.professeur_id = ? GROUP BY d.id ORDER BY d.date_ouverture DESC''',
        (session['utilisateur_id'],),
    ).fetchall()
    return render_template('dashboard.html', utilisateur=utilisateur, role='PROFESSEUR', classes=classes, devoirs=devoirs)


@app.route('/professeur/classe/nouvelle', methods=['GET', 'POST'])
@role_requis('PROFESSEUR')
def nouvelle_classe():
    if request.method == 'POST':
        nom = request.form.get('nom', '').strip()
        if not nom:
            return render_template('formulaire.html', type_formulaire='classe', error='Le nom est obligatoire.')
        code = secrets.token_hex(3).upper()
        db = get_db()
        db.execute('INSERT INTO classes (nom, professeur_id, code) VALUES (?, ?, ?)', (nom, session['utilisateur_id'], code))
        db.commit()
        return redirect(url_for('dashboard_professeur'))
    return render_template('formulaire.html', type_formulaire='classe')


@app.post('/eleve/classe/rejoindre')
@role_requis('ELEVE')
def rejoindre_classe():
    code = ''.join(char for char in request.form.get('code', '').upper() if char.isalnum())
    classe = get_db().execute('SELECT id FROM classes WHERE code = ?', (code,)).fetchone()
    if classe is None:
        return 'Code de classe invalide. Vérifiez le code transmis par le professeur.', 404
    db = get_db()
    db.execute('INSERT OR IGNORE INTO classe_eleves (classe_id, eleve_id) VALUES (?, ?)', (classe['id'], session['utilisateur_id']))
    db.commit()
    return redirect(url_for('dashboard_eleve'))


@app.route('/professeur/devoir/nouveau', methods=['GET', 'POST'])
@role_requis('PROFESSEUR')
def nouveau_devoir():
    db = get_db()
    classes = db.execute('SELECT id, nom FROM classes WHERE professeur_id = ? ORDER BY nom', (session['utilisateur_id'],)).fetchall()
    if request.method == 'POST':
        titre = request.form.get('titre', '').strip()
        classe_id = request.form.get('classe_id', type=int)
        duree = request.form.get('duree', type=int)
        ouverture = request.form.get('date_ouverture', '').strip()
        sujet = request.files.get('sujet')
        classe = db.execute('SELECT id FROM classes WHERE id = ? AND professeur_id = ?', (classe_id, session['utilisateur_id'])).fetchone()
        if not titre or classe is None or not duree or duree < 60 or not ouverture or sujet is None or not extension_autorisee(sujet.filename):
            return render_template('formulaire.html', type_formulaire='devoir', classes=classes, error='Tous les champs sont obligatoires. La duree minimale est de 60 secondes.')
        try:
            datetime.fromisoformat(ouverture)
        except ValueError:
            return render_template('formulaire.html', type_formulaire='devoir', classes=classes, error='Date d’ouverture invalide.')
        nom_sujet = secure_filename(sujet.filename)
        dossier = os.path.join(app.config['UPLOAD_FOLDER'], 'sujets')
        os.makedirs(dossier, exist_ok=True)
        sujet.save(os.path.join(dossier, nom_sujet))
        db.execute(
            '''INSERT INTO devoirs (titre, description, professeur_id, classe_id, sujet_pdf, date_ouverture, duree)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (titre, request.form.get('description', '').strip(), session['utilisateur_id'], classe_id, nom_sujet, ouverture, duree),
        )
        db.commit()
        return redirect(url_for('dashboard_professeur'))
    return render_template('formulaire.html', type_formulaire='devoir', classes=classes)


@app.get('/professeur/devoir/<int:devoir_id>/copies')
@role_requis('PROFESSEUR')
def voir_copies(devoir_id):
    devoir = get_db().execute(
        'SELECT * FROM devoirs WHERE id = ? AND professeur_id = ?',
        (devoir_id, session['utilisateur_id']),
    ).fetchone()
    if devoir is None:
        return 'Devoir introuvable.', 404
    copies = get_db().execute(
        '''SELECT s.*, u.nom AS eleve_nom, u.email AS eleve_email
           FROM sessions_examen s JOIN utilisateurs u ON u.id = s.eleve_id
           WHERE s.devoir_id = ? ORDER BY u.nom''',
        (devoir_id,),
    ).fetchall()
    return render_template('copies.html', devoir=devoir, copies=copies)


@app.post('/professeur/session/<int:session_id>/noter')
@role_requis('PROFESSEUR')
def noter_copie(session_id):
    note = request.form.get('note', '').strip()
    try:
        note = float(note)
        if not 0 <= note <= 20:
            raise ValueError
    except ValueError:
        return 'La note doit etre comprise entre 0 et 20.', 400
    db = get_db()
    examen = db.execute(
        '''SELECT s.id FROM sessions_examen s JOIN devoirs d ON d.id = s.devoir_id
           WHERE s.id = ? AND d.professeur_id = ?''',
        (session_id, session['utilisateur_id']),
    ).fetchone()
    if examen is None:
        return 'Copie introuvable.', 404
    db.execute('UPDATE sessions_examen SET note = ?, commentaire = ? WHERE id = ?', (note, request.form.get('commentaire', '').strip(), session_id))
    db.commit()
    return redirect(request.referrer or url_for('dashboard_professeur'))


def devoir_accessible(devoir_id):
    return get_db().execute(
        '''SELECT d.*, c.nom AS classe_nom FROM devoirs d
           JOIN classes c ON c.id = d.classe_id
           JOIN classe_eleves ce ON ce.classe_id = c.id
           WHERE d.id = ? AND ce.eleve_id = ?''',
        (devoir_id, session['utilisateur_id']),
    ).fetchone()


@app.post('/devoir/<int:devoir_id>/commencer')
@role_requis('ELEVE')
def commencer_devoir(devoir_id):
    devoir = devoir_accessible(devoir_id)
    if devoir is None:
        return 'Devoir introuvable.', 404
    maintenant = datetime.utcnow()
    ouverture = datetime.fromisoformat(devoir['date_ouverture'])
    if maintenant < ouverture:
        return 'Ce devoir n’est pas encore ouvert.', 403
    db = get_db()
    db.execute(
        'INSERT OR IGNORE INTO sessions_examen (eleve_id, devoir_id, heure_debut) VALUES (?, ?, ?)',
        (session['utilisateur_id'], devoir_id, maintenant.isoformat(timespec='seconds')),
    )
    db.commit()
    return redirect(url_for('voir_devoir', devoir_id=devoir_id))


@app.get('/devoir/<int:devoir_id>')
@role_requis('ELEVE')
def voir_devoir(devoir_id):
    devoir = devoir_accessible(devoir_id)
    if devoir is None:
        return 'Devoir introuvable.', 404
    examen = get_db().execute(
        'SELECT * FROM sessions_examen WHERE eleve_id = ? AND devoir_id = ?',
        (session['utilisateur_id'], devoir_id),
    ).fetchone()
    if examen is None:
        return redirect(url_for('dashboard_eleve'))
    fin = datetime.fromisoformat(examen['heure_debut']) + timedelta(seconds=devoir['duree'])
    restant = max(0, int((fin - datetime.utcnow()).total_seconds()))
    return render_template('devoir.html', devoir=devoir, restant=restant, examen=examen)


def extension_autorisee(nom_fichier):
    return '.' in nom_fichier and nom_fichier.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.post('/rendre_copie')
@connexion_requise
def rendre_copie():
    devoir_id = request.form.get('devoir_id', type=int)
    if devoir_id is None:
        return 'Devoir invalide.', 400
    devoir = devoir_accessible(devoir_id)
    examen = get_db().execute(
        'SELECT * FROM sessions_examen WHERE eleve_id = ? AND devoir_id = ?',
        (session['utilisateur_id'], devoir_id),
    ).fetchone()
    if devoir is None or examen is None:
        return 'Session invalide.', 403
    fin = datetime.fromisoformat(examen['heure_debut']) + timedelta(seconds=devoir['duree'])
    if datetime.utcnow() >= fin:
        return 'Le temps est ecoule.', 403
    copie = request.files.get('copie')
    if copie is None or not copie.filename:
        return 'Aucun fichier selectionne.', 400
    if not extension_autorisee(copie.filename):
        return 'Format non autorise. Utilisez un PDF, JPG ou PNG.', 400

    dossier = os.path.join(app.config['UPLOAD_FOLDER'], 'copies', str(devoir_id))
    os.makedirs(dossier, exist_ok=True)
    nom_fichier = secure_filename(f"{session['utilisateur_id']}_{copie.filename}")
    copie.save(os.path.join(dossier, nom_fichier))
    get_db().execute(
        "UPDATE sessions_examen SET fichier_copie = ?, heure_fin = ?, statut = 'TERMINE' WHERE id = ?",
        (nom_fichier, datetime.utcnow().isoformat(timespec='seconds'), examen['id']),
    )
    get_db().commit()
    return redirect(url_for('copie_deposee'))


@app.get('/copie-deposee')
def copie_deposee():
    return 'Votre copie a bien ete deposee.'


@app.get('/uploads/<path:nom_fichier>')
def telecharger_fichier(nom_fichier):
    return send_from_directory(app.config['UPLOAD_FOLDER'], nom_fichier)


if __name__ == '__main__':
    app.run(debug=True)