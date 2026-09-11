import os
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, abort, current_app, flash, g, redirect, render_template, request, send_from_directory, session, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_login.config import COOKIE_DURATION, COOKIE_HTTPONLY, COOKIE_NAME, COOKIE_SAMESITE, COOKIE_SECURE
from flask_login.utils import encode_cookie
from authlib.integrations.flask_client import OAuth
from authlib.integrations.base_client.errors import OAuthError
from joserfc import jwt
from joserfc.jwk import ECKey
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
configured_secret_key = os.environ.get('CLASSEXP_SECRET_KEY')
if os.environ.get('CLASSEXP_HTTPS') == '1' and not configured_secret_key:
    raise RuntimeError('CLASSEXP_SECRET_KEY est obligatoire en production HTTPS.')
app.config['SECRET_KEY'] = configured_secret_key or secrets.token_hex(32)
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
app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID')
app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET')
app.config['FACEBOOK_CLIENT_ID'] = os.environ.get('FACEBOOK_CLIENT_ID')
app.config['FACEBOOK_CLIENT_SECRET'] = os.environ.get('FACEBOOK_CLIENT_SECRET')
app.config['FACEBOOK_API_VERSION'] = os.environ.get('FACEBOOK_API_VERSION', 'v25.0')
app.config['APPLE_CLIENT_ID'] = os.environ.get('APPLE_CLIENT_ID')
app.config['APPLE_TEAM_ID'] = os.environ.get('APPLE_TEAM_ID')
app.config['APPLE_KEY_ID'] = os.environ.get('APPLE_KEY_ID')
app.config['APPLE_PRIVATE_KEY_PATH'] = os.environ.get('APPLE_PRIVATE_KEY_PATH')
app.config['MICROSOFT_CLIENT_ID'] = os.environ.get('MICROSOFT_CLIENT_ID')
app.config['MICROSOFT_CLIENT_SECRET'] = os.environ.get('MICROSOFT_CLIENT_SECRET')
app.config['MICROSOFT_TENANT'] = os.environ.get('MICROSOFT_TENANT', 'common')
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'png', 'docx'}
SUBMISSION_GRACE_SECONDS = 5 * 60

PROVIDERS = {
    'google': {'label': 'Google', 'oidc': True},
    'facebook': {'label': 'Facebook', 'oidc': False},
    'apple': {'label': 'Apple', 'oidc': True},
    'microsoft': {'label': 'Microsoft', 'oidc': True},
}


def apple_client_secret():
    path = app.config.get('APPLE_PRIVATE_KEY_PATH')
    if not path or not os.path.isfile(path):
        return None
    now = int(datetime.now(timezone.utc).timestamp())
    with open(path, 'rb') as key_file:
        key = key_file.read()
    claims = {
        'iss': app.config['APPLE_TEAM_ID'], 'iat': now, 'exp': now + 86400 * 30,
        'aud': 'https://appleid.apple.com', 'sub': app.config['APPLE_CLIENT_ID'],
    }
    return jwt.encode(
        {'alg': 'ES256', 'kid': app.config['APPLE_KEY_ID']}, claims,
        ECKey.import_key(key), algorithms=['ES256'],
    )


def provider_configured(provider):
    if provider == 'apple':
        return all(app.config.get(key) for key in (
            'APPLE_CLIENT_ID', 'APPLE_TEAM_ID', 'APPLE_KEY_ID', 'APPLE_PRIVATE_KEY_PATH'
        )) and os.path.isfile(app.config['APPLE_PRIVATE_KEY_PATH'])
    prefix = provider.upper()
    return bool(app.config.get(f'{prefix}_CLIENT_ID') and app.config.get(f'{prefix}_CLIENT_SECRET'))


oauth = OAuth(app)
oauth.register(
    'google', server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile', 'code_challenge_method': 'S256'},
)
if provider_configured('apple'):
    # Apple returns scopes with a cross-site form POST; its state cookie therefore
    # requires SameSite=None and Secure. Apple itself also requires an HTTPS domain.
    app.config['SESSION_COOKIE_SAMESITE'] = 'None'
    app.config['SESSION_COOKIE_SECURE'] = True
facebook_version = app.config['FACEBOOK_API_VERSION']
oauth.register(
    'facebook', authorize_url=f'https://www.facebook.com/{facebook_version}/dialog/oauth',
    access_token_url=f'https://graph.facebook.com/{facebook_version}/oauth/access_token',
    api_base_url=f'https://graph.facebook.com/{facebook_version}/',
    client_kwargs={'scope': 'email', 'code_challenge_method': 'S256'},
)
oauth.register(
    'apple', client_secret=apple_client_secret(),
    server_metadata_url='https://appleid.apple.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email name', 'token_endpoint_auth_method': 'client_secret_post'},
)
oauth.register(
    'microsoft',
    server_metadata_url=(
        f"https://login.microsoftonline.com/{app.config['MICROSOFT_TENANT']}"
        '/v2.0/.well-known/openid-configuration'
    ),
    client_kwargs={'scope': 'openid email profile', 'code_challenge_method': 'S256'},
)


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


def migrate_auth_schema():
    """Add external identities without changing existing user IDs or data."""
    with app.app_context():
        db = get_db()
        before = db.execute('SELECT COUNT(*) FROM utilisateurs').fetchone()[0]
        columns = {row['name']: row for row in db.execute('PRAGMA table_info(utilisateurs)')}
        if columns['mot_de_passe_hash']['notnull']:
            db.commit()
            db.execute('PRAGMA foreign_keys = OFF')
            try:
                db.execute('BEGIN IMMEDIATE')
                db.execute('''CREATE TABLE utilisateurs_auth_migration (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nom TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    mot_de_passe_hash TEXT,
                    role TEXT CHECK(role IN ('ELEVE', 'PROFESSEUR')) NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )''')
                db.execute('''INSERT INTO utilisateurs_auth_migration
                    (id, nom, email, mot_de_passe_hash, role)
                    SELECT id, nom, email, mot_de_passe_hash, role FROM utilisateurs''')
                db.execute('DROP TABLE utilisateurs')
                db.execute('ALTER TABLE utilisateurs_auth_migration RENAME TO utilisateurs')
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.execute('PRAGMA foreign_keys = ON')
        elif 'created_at' not in columns:
            db.execute('ALTER TABLE utilisateurs ADD COLUMN created_at TEXT')
            db.execute('UPDATE utilisateurs SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL')

        db.execute('''CREATE TABLE IF NOT EXISTS identites_externes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            utilisateur_id INTEGER NOT NULL,
            provider TEXT NOT NULL CHECK(provider IN ('google', 'facebook', 'apple', 'microsoft')),
            provider_subject TEXT NOT NULL,
            email_provider TEXT,
            email_verified INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_login_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (utilisateur_id) REFERENCES utilisateurs(id) ON DELETE CASCADE,
            UNIQUE (provider, provider_subject)
        )''')
        db.commit()
        after = db.execute('SELECT COUNT(*) FROM utilisateurs').fetchone()[0]
        foreign_key_errors = db.execute('PRAGMA foreign_key_check').fetchall()
        if before != after or foreign_key_errors:
            raise RuntimeError('La migration OAuth n\'a pas preserve les donnees existantes.')


ensure_db_initialized()
migrate_auth_schema()


def end_local_session():
    """Clear all app state and instruct Flask-Login to expire its remember cookie."""
    was_authenticated = current_user.is_authenticated
    session.clear()
    if was_authenticated:
        logout_user()


def replace_login(utilisateur, *, remember=False):
    end_local_session()
    login_user(Utilisateur(utilisateur), remember=remember)


def csrf_token():
    return session.setdefault('_csrf_token', secrets.token_urlsafe(32))


def valid_csrf():
    supplied = request.form.get('_csrf_token', '')
    expected = session.get('_csrf_token', '')
    return bool(expected and secrets.compare_digest(supplied, expected))


app.jinja_env.globals['csrf_token'] = csrf_token


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
        flash('Compte créé avec succès. Vous pouvez maintenant vous connecter.', 'success')
        return redirect(url_for('connexion'))

    return render_template('auth.html', mode='inscription')


@app.route('/connexion', methods=['GET', 'POST'])
def connexion():
    if request.method == 'GET':
        if request.args.get('switch') == '1':
            if current_user.is_authenticated:
                end_local_session()
            session['account_switch'] = True
        elif current_user.is_authenticated:
            return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        mot_de_passe = request.form.get('mot_de_passe', '')
        utilisateur = get_db().execute(
            'SELECT * FROM utilisateurs WHERE email = ?', (email,)
        ).fetchone()
        if (utilisateur is None or not utilisateur['mot_de_passe_hash']
                or not check_password_hash(utilisateur['mot_de_passe_hash'], mot_de_passe)):
            return render_template(
                'auth.html', mode='connexion', error='Email ou mot de passe incorrect.',
                providers=provider_status(), switch_mode=request.args.get('switch') == '1',
            )

        remember = bool(request.form.get('remember'))
        replace_login(utilisateur, remember=remember)
        return redirect(url_for('dashboard'))

    return render_template(
        'auth.html', mode='connexion', providers=provider_status(),
        switch_mode=request.args.get('switch') == '1',
    )


@app.get('/deconnexion')
@login_required
def deconnexion():
    end_local_session()
    return redirect(url_for('connexion'))


@app.get('/changer-compte')
@login_required
def changer_compte():
    end_local_session()
    session['account_switch'] = True
    return redirect(url_for('connexion', switch=1))


def provider_status():
    return [
        {'id': provider, 'label': details['label'], 'configured': provider_configured(provider)}
        for provider, details in PROVIDERS.items()
    ]


def normalized_truth(value):
    return value is True or str(value).lower() == 'true'


def exchange_external_profile(provider):
    """Exchange a validated code and return only the identity data ClasseXP needs."""
    client = oauth.create_client(provider)
    if provider == 'apple':
        client.client_secret = apple_client_secret()
    token = client.authorize_access_token()
    if provider == 'facebook':
        response = client.get('me?fields=id,name,email', token=token)
        response.raise_for_status()
        raw = response.json()
        subject = raw.get('id')
        return {
            'provider': provider, 'subject': subject, 'name': raw.get('name'),
            'email': raw.get('email'), 'email_verified': bool(raw.get('email')),
        }

    raw = dict(token.get('userinfo') or {})
    if provider == 'apple' and request.form.get('user'):
        try:
            first_login = json.loads(request.form['user'])
        except (TypeError, ValueError):
            first_login = {}
        apple_name = first_login.get('name') or {}
        raw['name'] = raw.get('name') or ' '.join(
            part for part in (apple_name.get('firstName'), apple_name.get('lastName')) if part
        )
        raw['email'] = raw.get('email') or first_login.get('email')
    return {
        'provider': provider, 'subject': raw.get('sub'), 'name': raw.get('name'),
        'email': raw.get('email'), 'email_verified': normalized_truth(raw.get('email_verified')),
    }


def external_identity_error(message, status=400):
    return render_template('oauth_error.html', message=message), status


@app.get('/auth/<provider>')
def external_login(provider):
    if provider not in PROVIDERS:
        abort(404)
    if not provider_configured(provider):
        return external_identity_error(f"{PROVIDERS[provider]['label']} n'est pas configure.", 503)
    linking = request.args.get('link') == '1'
    if linking:
        if not current_user.is_authenticated:
            return redirect(url_for('connexion'))
        session['oauth_link_user_id'] = current_user.id
    elif current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    client = oauth.create_client(provider)
    if provider == 'apple':
        client.client_secret = apple_client_secret()
    redirect_uri = url_for('external_callback', provider=provider, _external=True)
    params = {'nonce': secrets.token_urlsafe(32)} if PROVIDERS[provider].get('oidc') else {}
    if provider == 'apple':
        params.update(response_mode='form_post', response_type='code')
    if session.get('account_switch'):
        if provider == 'google':
            params['prompt'] = 'select_account'
        elif provider == 'microsoft':
            params['prompt'] = 'select_account'
        elif provider == 'facebook':
            params['auth_type'] = 'reauthorize'
    return client.authorize_redirect(redirect_uri, **params)


@app.route('/auth/<provider>/callback', methods=['GET', 'POST'])
def external_callback(provider):
    if provider not in PROVIDERS:
        abort(404)
    if not request.values.get('code'):
        return external_identity_error('Le fournisseur n\'a retourne aucun code d\'autorisation.')
    try:
        profile = exchange_external_profile(provider)
    except OAuthError:
        return external_identity_error('La reponse OAuth est invalide ou a expire.')
    except Exception:
        current_app.logger.exception('Echec OAuth pour %s (aucun jeton journalise)', provider)
        return external_identity_error('Impossible de valider cette connexion externe.')
    if not profile.get('subject'):
        return external_identity_error('Le fournisseur n\'a pas retourne d\'identifiant stable.')

    db = get_db()
    identity = db.execute(
        '''SELECT ie.id AS identity_id, ie.utilisateur_id, u.* FROM identites_externes ie
           JOIN utilisateurs u ON u.id = ie.utilisateur_id
           WHERE ie.provider = ? AND ie.provider_subject = ?''',
        (provider, profile['subject']),
    ).fetchone()
    linking_user_id = session.pop('oauth_link_user_id', None)
    if linking_user_id is not None:
        if not current_user.is_authenticated or current_user.id != int(linking_user_id):
            return external_identity_error('La session de liaison n\'est plus valide.', 403)
        if identity is not None and identity['utilisateur_id'] != current_user.id:
            return external_identity_error('Cette identite externe appartient deja a un autre compte.', 409)
        if identity is None:
            db.execute(
                '''INSERT INTO identites_externes
                   (utilisateur_id, provider, provider_subject, email_provider, email_verified)
                   VALUES (?, ?, ?, ?, ?)''',
                (current_user.id, provider, profile['subject'], profile.get('email'),
                 int(profile.get('email_verified', False))),
            )
            db.commit()
            flash(f"{PROVIDERS[provider]['label']} a été lié à votre compte.", 'success')
        else:
            flash(f"{PROVIDERS[provider]['label']} est déjà lié à votre compte.", 'info')
        return redirect(url_for('mon_compte'))

    if identity is not None:
        db.execute(
            '''UPDATE identites_externes SET last_login_at = CURRENT_TIMESTAMP,
               email_provider = COALESCE(?, email_provider), email_verified = ? WHERE id = ?''',
            (profile.get('email'), int(profile.get('email_verified', False)), identity['identity_id']),
        )
        db.commit()
        replace_login(identity, remember=True)
        return redirect(url_for('dashboard'))

    session['pending_external_identity'] = profile
    existing = None
    if profile.get('email'):
        existing = db.execute(
            'SELECT id FROM utilisateurs WHERE lower(email) = lower(?)', (profile['email'],)
        ).fetchone()
    if existing is not None:
        return redirect(url_for('lier_compte_existant'))
    return redirect(url_for('finaliser_compte'))


def pending_external_identity():
    pending = session.get('pending_external_identity')
    if not pending or pending.get('provider') not in PROVIDERS or not pending.get('subject'):
        return None
    return pending


@app.route('/auth/finaliser', methods=['GET', 'POST'])
def finaliser_compte():
    pending = pending_external_identity()
    if pending is None:
        return redirect(url_for('connexion'))
    error = None
    if request.method == 'POST':
        if not valid_csrf():
            abort(400)
        nom = request.form.get('nom', '').strip()
        email = (pending.get('email') or request.form.get('email', '')).strip().lower()
        role = request.form.get('role')
        if not nom or not email or role not in {'ELEVE', 'PROFESSEUR'}:
            error = 'Completez le nom, l\'adresse email et le role.'
        elif get_db().execute('SELECT 1 FROM utilisateurs WHERE lower(email) = lower(?)', (email,)).fetchone():
            pending['email'] = email
            session['pending_external_identity'] = pending
            return redirect(url_for('lier_compte_existant'))
        else:
            db = get_db()
            try:
                cursor = db.execute(
                    'INSERT INTO utilisateurs (nom, email, mot_de_passe_hash, role) VALUES (?, ?, NULL, ?)',
                    (nom, email, role),
                )
                db.execute(
                    '''INSERT INTO identites_externes
                       (utilisateur_id, provider, provider_subject, email_provider, email_verified)
                       VALUES (?, ?, ?, ?, ?)''',
                    (cursor.lastrowid, pending['provider'], pending['subject'], pending.get('email'),
                     int(pending.get('email_verified', False))),
                )
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                return external_identity_error('Cette identite est deja associee a un compte.', 409)
            utilisateur = db.execute('SELECT * FROM utilisateurs WHERE id = ?', (cursor.lastrowid,)).fetchone()
            replace_login(utilisateur, remember=True)
            flash('Compte ClasseXP créé avec succès.', 'success')
            return redirect(url_for('dashboard'))
    return render_template('oauth_finalize.html', pending=pending, error=error)


@app.route('/auth/lier-compte-existant', methods=['GET', 'POST'])
def lier_compte_existant():
    pending = pending_external_identity()
    if pending is None or not pending.get('email'):
        return redirect(url_for('connexion'))
    error = None
    if request.method == 'POST':
        if not valid_csrf():
            abort(400)
        db = get_db()
        utilisateur = db.execute(
            'SELECT * FROM utilisateurs WHERE lower(email) = lower(?)', (pending['email'],)
        ).fetchone()
        password = request.form.get('mot_de_passe', '')
        if (utilisateur is None or not utilisateur['mot_de_passe_hash']
                or not check_password_hash(utilisateur['mot_de_passe_hash'], password)):
            error = 'Mot de passe ClasseXP incorrect.'
        elif request.form.get('confirm_link') != '1':
            error = 'Confirmez explicitement la liaison du fournisseur.'
        else:
            try:
                db.execute(
                    '''INSERT INTO identites_externes
                       (utilisateur_id, provider, provider_subject, email_provider, email_verified)
                       VALUES (?, ?, ?, ?, ?)''',
                    (utilisateur['id'], pending['provider'], pending['subject'], pending.get('email'),
                     int(pending.get('email_verified', False))),
                )
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                return external_identity_error('Cette identite est deja associee a un compte.', 409)
            replace_login(utilisateur, remember=True)
            flash(f"{PROVIDERS[pending['provider']]['label']} a été lié à votre compte.", 'success')
            return redirect(url_for('mon_compte'))
    return render_template('oauth_link_existing.html', pending=pending, error=error)


@app.get('/mon-compte')
@login_required
def mon_compte():
    utilisateur = get_db().execute('SELECT * FROM utilisateurs WHERE id = ?', (current_user.id,)).fetchone()
    linked = {
        row['provider'] for row in get_db().execute(
            'SELECT provider FROM identites_externes WHERE utilisateur_id = ?', (current_user.id,)
        )
    }
    return render_template(
        'account.html', utilisateur=utilisateur, linked=linked, providers=provider_status(),
    )


@app.post('/mon-compte/delier/<provider>')
@login_required
def delier_fournisseur(provider):
    if provider not in PROVIDERS:
        abort(404)
    if not valid_csrf():
        abort(400)
    db = get_db()
    utilisateur = db.execute('SELECT mot_de_passe_hash FROM utilisateurs WHERE id = ?', (current_user.id,)).fetchone()
    identity_count = db.execute(
        'SELECT COUNT(*) FROM identites_externes WHERE utilisateur_id = ?', (current_user.id,)
    ).fetchone()[0]
    if not utilisateur['mot_de_passe_hash'] and identity_count <= 1:
        return external_identity_error('Impossible de delier votre derniere methode de connexion.', 409)
    db.execute(
        'DELETE FROM identites_externes WHERE utilisateur_id = ? AND provider = ?',
        (current_user.id, provider),
    )
    db.commit()
    flash(f"{PROVIDERS[provider]['label']} a été délié de votre compte.", 'success')
    return redirect(url_for('mon_compte'))


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
        flash('Classe créée avec succès.', 'success')
        return redirect(url_for('dashboard_professeur'))
    return render_template('formulaire.html', type_formulaire='classe')


@app.post('/eleve/classe/rejoindre')
@role_requis('ELEVE')
def rejoindre_classe():
    code = ''.join(char for char in request.form.get('code', '').upper() if char.isalnum())
    classe = get_db().execute('SELECT id FROM classes WHERE code = ?', (code,)).fetchone()
    if classe is None:
        flash('Code de classe invalide. Vérifiez le code transmis par le professeur.', 'error')
        return redirect(url_for('dashboard_eleve'))
    db = get_db()
    cursor = db.execute('INSERT OR IGNORE INTO classe_eleves (classe_id, eleve_id) VALUES (?, ?)', (classe['id'], current_user.id))
    db.commit()
    if cursor.rowcount:
        flash('Classe rejointe avec succès.', 'success')
    else:
        flash('Vous êtes déjà membre de cette classe.', 'info')
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
        flash('Devoir créé avec succès.', 'success')
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
    db = get_db()
    examen = db.execute(
        '''SELECT s.id, s.devoir_id FROM sessions_examen s JOIN devoirs d ON d.id = s.devoir_id
           WHERE s.id = ? AND d.professeur_id = ?''',
        (session_id, current_user.id),
    ).fetchone()
    if examen is None:
        return 'Copie introuvable.', 404
    note = request.form.get('note', '').strip()
    try:
        note = float(note)
        if not 0 <= note <= 20:
            raise ValueError
    except ValueError:
        flash('La note doit être comprise entre 0 et 20.', 'error')
        return redirect(url_for('voir_copies', devoir_id=examen['devoir_id']))
    db.execute('UPDATE sessions_examen SET note = ?, commentaire = ? WHERE id = ?', (note, request.form.get('commentaire', '').strip(), session_id))
    db.commit()
    flash('Note et correction enregistrées.', 'success')
    return redirect(url_for('voir_copies', devoir_id=examen['devoir_id']))


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
    fin_travail = datetime.fromisoformat(examen['heure_debut']) + timedelta(seconds=devoir['duree'])
    fin_remise = fin_travail + timedelta(seconds=SUBMISSION_GRACE_SECONDS)
    maintenant = utc_now()
    restant = max(0, int((fin_travail - maintenant).total_seconds()))
    remise_restant = max(0, int((fin_remise - maintenant).total_seconds()))
    return render_template(
        'devoir.html', devoir=devoir, restant=restant,
        remise_restant=remise_restant, examen=examen,
    )


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
        flash("Impossible d'envoyer la copie : devoir invalide.", 'error')
        return redirect(url_for('dashboard_eleve'))
    devoir = devoir_accessible(devoir_id)
    examen = get_db().execute(
        'SELECT * FROM sessions_examen WHERE eleve_id = ? AND devoir_id = ?',
        (current_user.id, devoir_id),
    ).fetchone()
    if devoir is None or examen is None:
        return 'Session invalide.', 403
    fin_travail = datetime.fromisoformat(examen['heure_debut']) + timedelta(seconds=devoir['duree'])
    fin_remise = fin_travail + timedelta(seconds=SUBMISSION_GRACE_SECONDS)
    if utc_now() >= fin_remise:
        flash("Le délai de remise de 5 minutes est écoulé. La copie n'a pas été envoyée.", 'warning')
        return redirect(url_for('dashboard_eleve'))
    copie = request.files.get('copie')
    if copie is None or not copie.filename:
        flash("Impossible d'envoyer la copie : aucun fichier sélectionné.", 'error')
        return redirect(url_for('voir_devoir', devoir_id=devoir_id))
    nom_fichier = nom_stockage_unique(copie.filename)
    if nom_fichier is None:
        flash('Format non autorisé. Utilisez un PDF, DOCX, JPG ou PNG.', 'error')
        return redirect(url_for('voir_devoir', devoir_id=devoir_id))

    dossier = os.path.join(app.config['UPLOAD_FOLDER'], 'copies', str(devoir_id))
    os.makedirs(dossier, exist_ok=True)
    copie.save(os.path.join(dossier, nom_fichier))
    get_db().execute(
        "UPDATE sessions_examen SET fichier_copie = ?, heure_fin = ?, statut = 'TERMINE' WHERE id = ?",
        (nom_fichier, utc_now().isoformat(timespec='seconds'), examen['id']),
    )
    get_db().commit()
    flash('Copie envoyée avec succès.', 'success')
    return redirect(url_for('voir_devoir', devoir_id=devoir_id))


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
