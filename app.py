import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, abort, current_app, g, redirect, render_template, request, send_from_directory, session, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_login.config import COOKIE_DURATION, COOKIE_HTTPONLY, COOKIE_NAME, COOKIE_SAMESITE, COOKIE_SECURE
from flask_login.utils import encode_cookie
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('CLASSEXP_SECRET_KEY', 'dev-secret-change-me')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'uploads')
app.config['DATABASE'] = os.path.join(app.root_path, 'database', 'classexp.db')
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=30)
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'
app.config['REMEMBER_COOKIE_SECURE'] = os.environ.get('CLASSEXP_HTTPS') == '1'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('CLASSEXP_HTTPS') == '1'
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'png', 'docx'}


class ClasseXPLoginManager(LoginManager):
    """Flask-Login 0.6.3 cookie writer without its deprecated utcnow call."""

    def _set_cookie(self, response):
        if '_user_id' not in session:
            return
        config = current_app.config
        cookie_name = config.get('REMEMBER_COOKIE_NAME', COOKIE_NAME)
        domain = config.get('REMEMBER_COOKIE_DOMAIN')
        path = config.get('REMEMBER_COOKIE_PATH', '/')
        secure = config.get('REMEMBER_COOKIE_SECURE', COOKIE_SECURE)
        httponly = config.get('REMEMBER_COOKIE_HTTPONLY', COOKIE_HTTPONLY)
        samesite = config.get('REMEMBER_COOKIE_SAMESITE', COOKIE_SAMESITE)
        duration = (
            timedelta(seconds=session['_remember_seconds'])
            if '_remember_seconds' in session
            else config.get('REMEMBER_COOKIE_DURATION', COOKIE_DURATION)
        )
        if isinstance(duration, int):
            duration = timedelta(seconds=duration)
        expires = datetime.now(timezone.utc) + duration
        response.set_cookie(
            cookie_name, value=encode_cookie(str(session['_user_id'])), expires=expires,
            domain=domain, path=path, secure=secure, httponly=httponly, samesite=samesite,
        )


login_manager = ClasseXPLoginManager(app)
login_manager.login_view = 'connexion'
login_manager.login_message = None
login_manager.session_protection = 'strong'


class Utilisateur(UserMixin):
    """Minimal Flask-Login user backed by the existing SQLite row."""

    def __init__(self, row):
        self.id = int(row['id'])
        self.nom = row['nom']
        self.email = row['email']
        self.role = row['role']

    def __getitem__(self, key):
        return getattr(self, key)


def utc_now():
    """Return naive UTC to stay compatible with existing SQLite values."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        database_path = current_app.config['DATABASE']
        os.makedirs(os.path.dirname(database_path), exist_ok=True)
        db = g._database = sqlite3.connect(database_path)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


@login_manager.user_loader
def load_user(user_id):
    try:
        utilisateur_id = int(user_id)
    except (TypeError, ValueError):
        return None
    row = get_db().execute(
        'SELECT id, nom, email, role FROM utilisateurs WHERE id = ?', (utilisateur_id,)
    ).fetchone()
    return Utilisateur(row) if row is not None else None


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


@app.context_processor
def inject_navigation_context():
    """Expose the signed-in user to the shared application shell."""
    if not current_user.is_authenticated:
        return {}
    return {'nav_utilisateur': current_user, 'nav_role': current_user.role}


@app.cli.command('init-db')
def init_db_command():
    """Efface les donnees existantes et cree les tables."""
    init_db()
    print('La base de donnees ClasseXP a ete initialisee avec succes.')


@app.route('/')
def accueil():
    return render_template('home.html')


@app.route('/inscription', methods=['GET', 'POST'])
def inscription():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        nom = request.form.get('nom', '').strip()
        email = request.form.get('email', '').strip().lower()
        mot_de_passe = request.form.get('mot_de_passe', '')
        role = request.form.get('role', 'ELEVE')

        if not nom or not email or len(mot_de_passe) < 8:
            return render_template('auth.html', mode='inscription', error='Remplissez tous les champs. Le mot de passe doit contenir 8 caracteres minimum.')
        if role not in {'ELEVE', 'PROFESSEUR'}:
            return render_template('auth.html', mode='inscription', error='Role invalide.')

        db = get_db()
        if db.execute('SELECT 1 FROM utilisateurs WHERE email = ?', (email,)).fetchone() is not None:
            return render_template(
                'auth.html', mode='inscription', compte_existant=True,
                error='Un compte existe deja avec cette adresse email.',
            )

        try:
            db.execute(
                'INSERT INTO utilisateurs (nom, email, mot_de_passe_hash, role) VALUES (?, ?, ?, ?)',
                (nom, email, generate_password_hash(mot_de_passe), role),
            )
            db.commit()
        except sqlite3.IntegrityError:
            return render_template(
                'auth.html', mode='inscription', compte_existant=True,
                error='Un compte existe deja avec cette adresse email.',
            )
        return redirect(url_for('connexion'))

    return render_template('auth.html', mode='inscription')


@app.route('/connexion', methods=['GET', 'POST'])
def connexion():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        mot_de_passe = request.form.get('mot_de_passe', '')
        utilisateur = get_db().execute(
            'SELECT * FROM utilisateurs WHERE email = ?', (email,)
        ).fetchone()
        if utilisateur is None or not check_password_hash(utilisateur['mot_de_passe_hash'], mot_de_passe):
            return render_template('auth.html', mode='connexion', error='Email ou mot de passe incorrect.')

        remember = bool(request.form.get('remember'))
        login_user(Utilisateur(utilisateur), remember=remember)
        return redirect(url_for('dashboard'))

    return render_template('auth.html', mode='connexion')


@app.get('/deconnexion')
@login_required
def deconnexion():
    logout_user()
    return redirect(url_for('connexion'))


def role_requis(role):
    def decorateur(route):
        @wraps(route)
        @login_required
        def route_protegee(*args, **kwargs):
            if current_user.role != role:
                if current_user.role == 'PROFESSEUR':
                    return redirect(url_for('dashboard_professeur'))
                if current_user.role == 'ELEVE':
                    return redirect(url_for('dashboard_eleve'))
                logout_user()
                return redirect(url_for('connexion'))
            return route(*args, **kwargs)
        return route_protegee
    return decorateur


@app.get('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'PROFESSEUR':
        return redirect(url_for('dashboard_professeur'))
    return redirect(url_for('dashboard_eleve'))


@app.get('/eleve')
@role_requis('ELEVE')
def dashboard_eleve():
    utilisateur = get_db().execute(
        'SELECT nom, email FROM utilisateurs WHERE id = ?', (current_user.id,)
    ).fetchone()
    devoirs = get_db().execute(
          '''SELECT d.*, c.nom AS classe_nom, s.note, s.commentaire,
                        s.statut, s.heure_debut, s.heure_fin, s.fichier_copie,
                        EXISTS(SELECT 1 FROM sessions_examen sx WHERE sx.devoir_id = d.id AND sx.eleve_id = ?) AS commence
           FROM devoirs d
           JOIN classes c ON c.id = d.classe_id
           JOIN classe_eleves ce ON ce.classe_id = c.id
              LEFT JOIN sessions_examen s ON s.devoir_id = d.id AND s.eleve_id = ?
           WHERE ce.eleve_id = ?
           ORDER BY d.date_ouverture DESC''',
          (current_user.id, current_user.id, current_user.id),
    ).fetchall()
    classes = get_db().execute(
        'SELECT c.nom, c.code FROM classes c JOIN classe_eleves ce ON ce.classe_id = c.id WHERE ce.eleve_id = ?',
        (current_user.id,),
    ).fetchall()
    devoirs_en_cours = sum(1 for devoir in devoirs if devoir['statut'] == 'EN_COURS')
    notes = [devoir['note'] for devoir in devoirs if devoir['note'] is not None]
    moyenne = round(sum(notes) / len(notes), 1) if notes else None
    return render_template(
        'dashboard.html', utilisateur=utilisateur, role='ELEVE', devoirs=devoirs,
        classes=classes, devoirs_en_cours=devoirs_en_cours, moyenne=moyenne,
    )


@app.get('/professeur')
@role_requis('PROFESSEUR')
def dashboard_professeur():
    utilisateur = get_db().execute(
        'SELECT nom, email FROM utilisateurs WHERE id = ?', (current_user.id,)
    ).fetchone()
    db = get_db()
    classes = db.execute(
        '''SELECT c.*, COUNT(ce.eleve_id) AS nombre_eleves
           FROM classes c LEFT JOIN classe_eleves ce ON ce.classe_id = c.id
           WHERE c.professeur_id = ? GROUP BY c.id ORDER BY c.nom''',
        (current_user.id,),
    ).fetchall()
    devoirs = db.execute(
        '''SELECT d.*, c.nom AS classe_nom,
                  COUNT(CASE WHEN s.fichier_copie IS NOT NULL THEN 1 END) AS copies,
                  COUNT(CASE WHEN s.fichier_copie IS NOT NULL AND s.note IS NULL THEN 1 END) AS a_corriger
           FROM devoirs d JOIN classes c ON c.id = d.classe_id
           LEFT JOIN sessions_examen s ON s.devoir_id = d.id AND s.fichier_copie IS NOT NULL
           WHERE d.professeur_id = ? GROUP BY d.id ORDER BY d.date_ouverture DESC''',
        (current_user.id,),
    ).fetchall()
    return render_template(
        'dashboard.html', utilisateur=utilisateur, role='PROFESSEUR',
        classes=classes, devoirs=devoirs,
    )


@app.route('/professeur/classe/nouvelle', methods=['GET', 'POST'])
@role_requis('PROFESSEUR')
def nouvelle_classe():
    if request.method == 'POST':
        nom = request.form.get('nom', '').strip()
        if not nom:
            return render_template('formulaire.html', type_formulaire='classe', error='Le nom est obligatoire.')
        code = secrets.token_hex(3).upper()
        db = get_db()
        db.execute('INSERT INTO classes (nom, professeur_id, code) VALUES (?, ?, ?)', (nom, current_user.id, code))
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
    db.execute('INSERT OR IGNORE INTO classe_eleves (classe_id, eleve_id) VALUES (?, ?)', (classe['id'], current_user.id))
    db.commit()
    return redirect(url_for('dashboard_eleve'))


@app.route('/professeur/devoir/nouveau', methods=['GET', 'POST'])
@role_requis('PROFESSEUR')
def nouveau_devoir():
    db = get_db()
    classes = db.execute('SELECT id, nom FROM classes WHERE professeur_id = ? ORDER BY nom', (current_user.id,)).fetchall()
    if request.method == 'POST':
        titre = request.form.get('titre', '').strip()
        classe_id = request.form.get('classe_id', type=int)
        duree = request.form.get('duree', type=int)
        ouverture = request.form.get('date_ouverture', '').strip()
        sujet = request.files.get('sujet')
        nom_sujet = nom_stockage_unique(sujet.filename) if sujet is not None else None
        classe = db.execute('SELECT id FROM classes WHERE id = ? AND professeur_id = ?', (classe_id, current_user.id)).fetchone()
        if not titre or classe is None or not duree or duree < 60 or not ouverture or sujet is None or nom_sujet is None:
            return render_template('formulaire.html', type_formulaire='devoir', classes=classes, error='Tous les champs sont obligatoires. La duree minimale est de 60 secondes.')
        try:
            datetime.fromisoformat(ouverture)
        except ValueError:
            return render_template('formulaire.html', type_formulaire='devoir', classes=classes, error='Date d’ouverture invalide.')
        dossier = os.path.join(app.config['UPLOAD_FOLDER'], 'sujets')
        os.makedirs(dossier, exist_ok=True)
        sujet.save(os.path.join(dossier, nom_sujet))
        db.execute(
            '''INSERT INTO devoirs (titre, description, professeur_id, classe_id, sujet_pdf, date_ouverture, duree)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (titre, request.form.get('description', '').strip(), current_user.id, classe_id, nom_sujet, ouverture, duree),
        )
        db.commit()
        return redirect(url_for('dashboard_professeur'))
    return render_template('formulaire.html', type_formulaire='devoir', classes=classes)


@app.get('/professeur/devoir/<int:devoir_id>/copies')
@role_requis('PROFESSEUR')
def voir_copies(devoir_id):
    devoir = get_db().execute(
        'SELECT * FROM devoirs WHERE id = ? AND professeur_id = ?',
        (devoir_id, current_user.id),
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
        (session_id, current_user.id),
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
        (devoir_id, current_user.id),
    ).fetchone()


@app.post('/devoir/<int:devoir_id>/commencer')
@role_requis('ELEVE')
def commencer_devoir(devoir_id):
    devoir = devoir_accessible(devoir_id)
    if devoir is None:
        return 'Devoir introuvable.', 404
    maintenant = utc_now()
    ouverture = datetime.fromisoformat(devoir['date_ouverture'])
    if maintenant < ouverture:
        return 'Ce devoir n’est pas encore ouvert.', 403
    db = get_db()
    db.execute(
        'INSERT OR IGNORE INTO sessions_examen (eleve_id, devoir_id, heure_debut) VALUES (?, ?, ?)',
        (current_user.id, devoir_id, maintenant.isoformat(timespec='seconds')),
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
        (current_user.id, devoir_id),
    ).fetchone()
    if examen is None:
        return redirect(url_for('dashboard_eleve'))
    fin = datetime.fromisoformat(examen['heure_debut']) + timedelta(seconds=devoir['duree'])
    restant = max(0, int((fin - utc_now()).total_seconds()))
    return render_template('devoir.html', devoir=devoir, restant=restant, examen=examen)


def extension_autorisee(nom_fichier):
    return '.' in nom_fichier and nom_fichier.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def nom_stockage_unique(nom_original):
    """Build an opaque storage name from a sanitized, allowed extension."""
    nom_securise = secure_filename(nom_original)
    if not extension_autorisee(nom_securise):
        return None
    extension = nom_securise.rsplit('.', 1)[1].lower()
    return f'{uuid.uuid4().hex}.{extension}'


@app.post('/rendre_copie')
@login_required
def rendre_copie():
    devoir_id = request.form.get('devoir_id', type=int)
    if devoir_id is None:
        return 'Devoir invalide.', 400
    devoir = devoir_accessible(devoir_id)
    examen = get_db().execute(
        'SELECT * FROM sessions_examen WHERE eleve_id = ? AND devoir_id = ?',
        (current_user.id, devoir_id),
    ).fetchone()
    if devoir is None or examen is None:
        return 'Session invalide.', 403
    fin = datetime.fromisoformat(examen['heure_debut']) + timedelta(seconds=devoir['duree'])
    if utc_now() >= fin:
        return 'Le temps est ecoule.', 403
    copie = request.files.get('copie')
    if copie is None or not copie.filename:
        return 'Aucun fichier selectionne.', 400
    nom_fichier = nom_stockage_unique(copie.filename)
    if nom_fichier is None:
        return 'Format non autorise. Utilisez un PDF, JPG ou PNG.', 400

    dossier = os.path.join(app.config['UPLOAD_FOLDER'], 'copies', str(devoir_id))
    os.makedirs(dossier, exist_ok=True)
    copie.save(os.path.join(dossier, nom_fichier))
    get_db().execute(
        "UPDATE sessions_examen SET fichier_copie = ?, heure_fin = ?, statut = 'TERMINE' WHERE id = ?",
        (nom_fichier, utc_now().isoformat(timespec='seconds'), examen['id']),
    )
    get_db().commit()
    return redirect(url_for('copie_deposee'))


@app.get('/copie-deposee')
@login_required
def copie_deposee():
    return 'Votre copie a bien ete deposee.'


@app.get('/uploads/<path:nom_fichier>')
@login_required
def telecharger_fichier(nom_fichier):
    parties = nom_fichier.replace('\\', '/').split('/')
    if len(parties) == 2 and parties[0] == 'sujets':
        if current_user.role == 'PROFESSEUR':
            autorise = get_db().execute(
                'SELECT 1 FROM devoirs WHERE sujet_pdf = ? AND professeur_id = ?',
                (parties[1], current_user.id),
            ).fetchone() is not None
        else:
            autorise = get_db().execute(
                '''SELECT 1 FROM devoirs d JOIN classe_eleves ce ON ce.classe_id = d.classe_id
                   WHERE d.sujet_pdf = ? AND ce.eleve_id = ?''',
                (parties[1], current_user.id),
            ).fetchone() is not None
    elif len(parties) == 3 and parties[0] == 'copies' and parties[1].isdigit():
        copie = get_db().execute(
            '''SELECT s.eleve_id, d.professeur_id FROM sessions_examen s
               JOIN devoirs d ON d.id = s.devoir_id
               WHERE s.devoir_id = ? AND s.fichier_copie = ?''',
            (int(parties[1]), parties[2]),
        ).fetchone()
        if copie is None:
            abort(404)
        autorise = (
            current_user.role == 'PROFESSEUR'
            and copie['professeur_id'] == current_user.id
        ) or (
            current_user.role == 'ELEVE'
            and copie['eleve_id'] == current_user.id
        )
    else:
        abort(404)
    if not autorise:
        abort(403)
    return send_from_directory(app.config['UPLOAD_FOLDER'], nom_fichier)


if __name__ == '__main__':
    app.run(debug=True)
