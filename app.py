import os
import json
import secrets
import uuid
import mimetypes
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Flask, abort, current_app, flash, g, redirect, render_template, request, session, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_login.config import COOKIE_DURATION, COOKIE_HTTPONLY, COOKIE_NAME, COOKIE_SAMESITE, COOKIE_SECURE
from flask_login.utils import encode_cookie
from authlib.integrations.flask_client import OAuth
from authlib.integrations.base_client.errors import OAuthError
from joserfc import jwt
from joserfc.jwk import ECKey
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from database import (
    close_db,
    create_schema,
    database_backend,
    database_ping,
    database_url_from_config,
    get_db,
    migration_version,
    validate_production_database,
)
from storage import StorageError, build_storage, required_r2_values, validate_production_storage

def resolve_secret_key(root_path):
    configured = os.environ.get('CLASSEXP_SECRET_KEY')
    environment = resolve_environment()
    if environment == 'production' and not configured:
        raise RuntimeError('CLASSEXP_SECRET_KEY est obligatoire et doit etre persistante en production.')
    if configured:
        return configured

    local_secret_path = os.path.join(root_path, '.classexp-secret-key')
    try:
        with open(local_secret_path, 'r', encoding='ascii') as secret_file:
            configured = secret_file.read().strip()
    except FileNotFoundError:
        configured = secrets.token_hex(32)
        with open(local_secret_path, 'x', encoding='ascii') as secret_file:
            secret_file.write(configured)
    return configured


def resolve_environment():
    configured = os.environ.get('CLASSEXP_ENV') or os.environ.get('FLASK_ENV')
    if configured:
        return configured.lower()
    if os.environ.get('RENDER'):
        return 'production'
    return 'development'


app = Flask(__name__)
load_dotenv(os.path.join(app.root_path, '.env'))
app.config['CLASSEXP_ENV'] = resolve_environment()
configured_secret_key = resolve_secret_key(app.root_path)
app.config['SECRET_KEY'] = configured_secret_key
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'uploads')
default_database_url = f"sqlite:///{os.path.join(app.root_path, 'database', 'classexp.db').replace(os.sep, '/')}"
app.config['DATABASE_URL'] = os.environ.get('DATABASE_URL') or (
    '' if app.config['CLASSEXP_ENV'] == 'production' else default_database_url
)
app.config['STORAGE_BACKEND'] = os.environ.get('STORAGE_BACKEND', 'local').lower()
for storage_setting in (
    'R2_ENDPOINT_URL', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET', 'R2_REGION'
):
    app.config[storage_setting] = os.environ.get(storage_setting)
app.config['R2_REGION'] = app.config['R2_REGION'] or 'auto'
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
ALLOWED_CONTENT_TYPES = {
    'pdf': {'application/pdf', 'application/octet-stream'},
    'jpg': {'image/jpeg', 'application/octet-stream'},
    'png': {'image/png', 'application/octet-stream'},
    'docx': {
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/octet-stream',
    },
}

validate_production_database(app.config['CLASSEXP_ENV'], app.config['DATABASE_URL'])
validate_production_storage(
    app.config['CLASSEXP_ENV'], app.config['STORAGE_BACKEND'], app.config
)
app.logger.info('Database backend: %s', database_backend(app.config['DATABASE_URL']).title())
app.logger.info('Storage backend: %s', app.config['STORAGE_BACKEND'].upper())

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


def get_storage():
    storage_service = getattr(g, '_storage_service', None)
    if storage_service is None:
        storage_service = g._storage_service = build_storage(current_app.config)
    return storage_service


@app.teardown_appcontext
def close_connection(exception):
    close_db(exception)


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
    create_schema(app.config, drop=True)


def ensure_db_initialized():
    if app.config.get('CLASSEXP_ENV') == 'production':
        return
    create_schema(app.config)


def migrate_auth_schema():
    """Compatibility shim: versioned migrations now own schema evolution."""
    ensure_db_initialized()


ensure_db_initialized()
app.logger.info('Migration version: %s', migration_version(app.config))


def end_local_session():
    """Clear all app state and instruct Flask-Login to expire its remember cookie."""
    was_authenticated = current_user.is_authenticated
    if was_authenticated:
        logout_user()
    remember_clear = session.get('_remember') == 'clear'
    session.clear()
    if remember_clear:
        session['_remember'] = 'clear'


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
    if app.config['CLASSEXP_ENV'] == 'production':
        raise RuntimeError('init-db est interdite en production; utilisez Alembic.')
    init_db()
    print('La base de donnees ClasseXP a ete initialisee avec succes.')


@app.cli.command('auth-status')
def auth_status_command():
    """Affiche l'etat de l'authentification sans exposer de secret."""
    secret_source = 'configured' if os.environ.get('CLASSEXP_SECRET_KEY') else 'persistent'
    print('Local authentication: READY')
    print(f'Secret key: {secret_source}')
    print(f'Database backend: {database_backend(database_url_from_config(app.config))}')
    base_url = os.environ.get('CLASSEXP_BASE_URL', 'http://127.0.0.1:5000')
    with app.test_request_context(base_url=base_url):
        for provider in PROVIDERS:
            state = 'READY' if provider_configured(provider) else 'NEEDS CONFIG'
            print(f'{PROVIDERS[provider]["label"]}: {state}')
            print(f'Callback: {url_for("external_callback", provider=provider, _external=True)}')


@app.cli.command('system-status')
def system_status_command():
    """Check production dependencies without exposing credentials."""
    environment = app.config['CLASSEXP_ENV']
    backend = database_backend(database_url_from_config(app.config))
    print(f'Environment: {environment}')
    print('\nDatabase:')
    print(f'  backend: {backend}')
    print('  configured: yes')
    print(f'  connection: {"ok" if database_ping(app.config) else "failed"}')
    print('\nStorage:')
    print(f'  backend: {app.config["STORAGE_BACKEND"]}')
    missing = required_r2_values(app.config) if app.config['STORAGE_BACKEND'] != 'local' else []
    print(f'  configured: {"no" if missing else "yes"}')
    try:
        storage_ok = not missing and get_storage().check()
    except StorageError:
        storage_ok = False
    print(f'  connection: {"ok" if storage_ok else "failed"}')
    print('\nSecret key:')
    persistent = bool(os.environ.get('CLASSEXP_SECRET_KEY')) or environment != 'production'
    print(f'  persistent: {"yes" if persistent else "no"}')
    with app.test_request_context(base_url=os.environ.get('CLASSEXP_BASE_URL', 'http://127.0.0.1:5000')):
        for provider in PROVIDERS:
            print(f'{PROVIDERS[provider]["label"]}: {"READY" if provider_configured(provider) else "NEEDS CONFIG"}')


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
            cursor = db.execute(
                'INSERT INTO utilisateurs (nom, email, mot_de_passe_hash, role) VALUES (?, ?, ?, ?) RETURNING id',
                (nom, email, generate_password_hash(mot_de_passe), role),
            )
            utilisateur_id = cursor.fetchone()['id']
            db.commit()
            if db.execute(
                'SELECT 1 FROM utilisateurs WHERE id = ?', (utilisateur_id,)
            ).fetchone() is None:
                raise SQLAlchemyError('Le compte n\'a pas ete persiste.')
        except IntegrityError:
            db.rollback()
            return render_template(
                'auth.html', mode='inscription', compte_existant=True,
                error='Un compte existe deja avec cette adresse email.',
            )
        except SQLAlchemyError:
            db.rollback()
            return render_template(
                'auth.html', mode='inscription',
                error='Impossible de creer le compte. Verifiez les donnees puis reessayez.',
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
                 bool(profile.get('email_verified', False))),
            )
            db.commit()
        return redirect(url_for('mon_compte'))

    if identity is not None:
        db.execute(
            '''UPDATE identites_externes SET last_login_at = CURRENT_TIMESTAMP,
               email_provider = COALESCE(?, email_provider), email_verified = ? WHERE id = ?''',
            (profile.get('email'), bool(profile.get('email_verified', False)), identity['identity_id']),
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
                    'INSERT INTO utilisateurs (nom, email, mot_de_passe_hash, role) VALUES (?, ?, NULL, ?) RETURNING id',
                    (nom, email, role),
                )
                utilisateur_id = cursor.fetchone()['id']
                db.execute(
                    '''INSERT INTO identites_externes
                       (utilisateur_id, provider, provider_subject, email_provider, email_verified)
                       VALUES (?, ?, ?, ?, ?)''',
                    (utilisateur_id, pending['provider'], pending['subject'], pending.get('email'),
                     bool(pending.get('email_verified', False))),
                )
                db.commit()
            except IntegrityError:
                db.rollback()
                return external_identity_error('Cette identite est deja associee a un compte.', 409)
            utilisateur = db.execute('SELECT * FROM utilisateurs WHERE id = ?', (utilisateur_id,)).fetchone()
            replace_login(utilisateur, remember=True)
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
                     bool(pending.get('email_verified', False))),
                )
                db.commit()
            except IntegrityError:
                db.rollback()
                return external_identity_error('Cette identite est deja associee a un compte.', 409)
            replace_login(utilisateur, remember=True)
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
           WHERE c.professeur_id = ? GROUP BY c.id, c.nom ORDER BY c.nom''',
        (current_user.id,),
    ).fetchall()
    devoirs = db.execute(
        '''SELECT d.*, c.nom AS classe_nom,
                  COUNT(CASE WHEN s.fichier_copie IS NOT NULL THEN 1 END) AS copies,
                  COUNT(CASE WHEN s.fichier_copie IS NOT NULL AND s.note IS NULL THEN 1 END) AS a_corriger
           FROM devoirs d JOIN classes c ON c.id = d.classe_id
           LEFT JOIN sessions_examen s ON s.devoir_id = d.id AND s.fichier_copie IS NOT NULL
           WHERE d.professeur_id = ? GROUP BY d.id, c.nom ORDER BY d.date_ouverture DESC''',
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
        if not contenu_fichier_valide(sujet, nom_sujet):
            return render_template(
                'formulaire.html', type_formulaire='devoir', classes=classes,
                error='Le type du fichier ne correspond pas a son extension.',
            )
        storage_key = None
        try:
            inserted = db.execute(
                '''INSERT INTO devoirs
                   (titre, description, professeur_id, classe_id, sujet_pdf, date_ouverture, duree)
                   VALUES (?, ?, ?, ?, NULL, ?, ?) RETURNING id''',
                (titre, request.form.get('description', '').strip(), current_user.id,
                 classe_id, ouverture, duree),
            ).fetchone()
            devoir_id = inserted['id']
            storage_key = f'subjects/devoir-{devoir_id}/{nom_sujet}'
            size = taille_fichier(sujet)
            get_storage().put(storage_key, sujet.stream, content_type=sujet.mimetype)
            db.execute('UPDATE devoirs SET sujet_pdf = ? WHERE id = ?', (storage_key, devoir_id))
            db.execute(
                '''INSERT INTO fichiers
                   (storage_key, original_filename, content_type, size, kind, owner_user_id, devoir_id)
                   VALUES (?, ?, ?, ?, 'SUJET', ?, ?)''',
                (storage_key, secure_filename(sujet.filename), sujet.mimetype or 'application/octet-stream',
                 size, current_user.id, devoir_id),
            )
            db.commit()
        except (StorageError, SQLAlchemyError):
            db.rollback()
            if storage_key:
                try:
                    get_storage().delete(storage_key)
                except StorageError:
                    current_app.logger.warning('Objet orphelin possible apres echec DB: %s', storage_key)
            current_app.logger.exception('Echec de creation du devoir et de son sujet')
            return render_template(
                'formulaire.html', type_formulaire='devoir', classes=classes,
                error="Impossible d'envoyer le fichier pour le moment. Reessayez dans quelques instants.",
            ), 503
        flash('Devoir cree.', 'success')
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


def taille_fichier(upload):
    position = upload.stream.tell()
    upload.stream.seek(0, os.SEEK_END)
    size = upload.stream.tell()
    upload.stream.seek(position)
    return size


def contenu_fichier_valide(upload, storage_name):
    extension = storage_name.rsplit('.', 1)[1]
    content_type = (upload.mimetype or '').lower()
    return taille_fichier(upload) > 0 and content_type in ALLOWED_CONTENT_TYPES[extension]


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

    if not contenu_fichier_valide(copie, nom_fichier):
        return 'Le type du fichier ne correspond pas a son extension.', 400
    storage_key = f'copies/devoir-{devoir_id}/eleve-{current_user.id}/{nom_fichier}'
    previous_key = examen['fichier_copie']
    db = get_db()
    try:
        size = taille_fichier(copie)
        get_storage().put(storage_key, copie.stream, content_type=copie.mimetype)
        db.execute(
            "UPDATE sessions_examen SET fichier_copie = ?, heure_fin = ?, statut = 'TERMINE' WHERE id = ?",
            (storage_key, utc_now().isoformat(timespec='seconds'), examen['id']),
        )
        db.execute('DELETE FROM fichiers WHERE session_id = ? AND kind = ?', (examen['id'], 'COPIE'))
        db.execute(
            '''INSERT INTO fichiers
               (storage_key, original_filename, content_type, size, kind, owner_user_id, devoir_id, session_id)
               VALUES (?, ?, ?, ?, 'COPIE', ?, ?, ?)''',
            (storage_key, secure_filename(copie.filename), copie.mimetype or 'application/octet-stream',
             size, current_user.id, devoir_id, examen['id']),
        )
        db.commit()
    except (StorageError, SQLAlchemyError):
        db.rollback()
        try:
            get_storage().delete(storage_key)
        except StorageError:
            current_app.logger.warning('Objet orphelin possible apres echec DB: %s', storage_key)
        current_app.logger.exception('Echec de depot de copie')
        return "Impossible d'envoyer le fichier pour le moment. Reessayez dans quelques instants.", 503
    if previous_key and previous_key != storage_key:
        try:
            get_storage().delete(normaliser_cle_legacy(previous_key, 'copies', devoir_id))
        except StorageError:
            current_app.logger.warning('Ancienne copie non supprimee: %s', previous_key)
    flash('Copie envoyee.', 'success')
    return redirect(url_for('dashboard_eleve'))


@app.get('/copie-deposee')
@login_required
def copie_deposee():
    return 'Votre copie a bien ete deposee.'


@app.get('/uploads/<path:nom_fichier>')
@login_required
def telecharger_fichier(nom_fichier):
    storage_key = nom_fichier.replace('\\', '/').lstrip('/')
    if '..' in storage_key.split('/'):
        abort(404)
    if storage_key.startswith('subjects/'):
        if current_user.role == 'PROFESSEUR':
            autorise = get_db().execute(
                'SELECT 1 FROM devoirs WHERE sujet_pdf = ? AND professeur_id = ?',
                (storage_key, current_user.id),
            ).fetchone() is not None
        else:
            autorise = get_db().execute(
                '''SELECT 1 FROM devoirs d JOIN classe_eleves ce ON ce.classe_id = d.classe_id
                   WHERE d.sujet_pdf = ? AND ce.eleve_id = ?''',
                (storage_key, current_user.id),
            ).fetchone() is not None
    elif storage_key.startswith('sujets/') and len(storage_key.split('/')) == 2:
        legacy_name = storage_key.split('/')[1]
        if current_user.role == 'PROFESSEUR':
            autorise = get_db().execute(
                'SELECT 1 FROM devoirs WHERE sujet_pdf = ? AND professeur_id = ?',
                (legacy_name, current_user.id),
            ).fetchone() is not None
        else:
            autorise = get_db().execute(
                '''SELECT 1 FROM devoirs d JOIN classe_eleves ce ON ce.classe_id = d.classe_id
                   WHERE d.sujet_pdf = ? AND ce.eleve_id = ?''',
                (legacy_name, current_user.id),
            ).fetchone() is not None
    elif storage_key.startswith('copies/'):
        copie = get_db().execute(
            '''SELECT s.eleve_id, d.professeur_id FROM sessions_examen s
               JOIN devoirs d ON d.id = s.devoir_id
               WHERE s.fichier_copie = ?''',
            (storage_key,),
        ).fetchone()
        if copie is None:
            legacy_parts = storage_key.split('/')
            if len(legacy_parts) == 3 and legacy_parts[1].isdigit():
                copie = get_db().execute(
                    '''SELECT s.eleve_id, d.professeur_id FROM sessions_examen s
                       JOIN devoirs d ON d.id = s.devoir_id
                       WHERE s.devoir_id = ? AND s.fichier_copie = ?''',
                    (int(legacy_parts[1]), legacy_parts[2]),
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
    metadata = get_db().execute(
        'SELECT original_filename, content_type FROM fichiers WHERE storage_key = ?',
        (storage_key,),
    ).fetchone()
    try:
        return get_storage().response(
            storage_key,
            download_name=metadata['original_filename'] if metadata else os.path.basename(storage_key),
            content_type=metadata['content_type'] if metadata else mimetypes.guess_type(storage_key)[0],
        )
    except FileNotFoundError:
        abort(404)
    except StorageError:
        current_app.logger.exception('Stockage indisponible pendant un telechargement')
        return 'Fichier temporairement indisponible.', 503


def normaliser_cle_legacy(key, kind, devoir_id=None):
    if '/' in key:
        return key
    if kind == 'copies':
        return f'copies/{devoir_id}/{key}'
    return f'sujets/{key}'


@app.get('/health')
def health():
    if database_ping(app.config):
        return {'status': 'ok', 'database': 'ok'}
    return {'status': 'error', 'database': 'unavailable'}, 503


@app.get('/ready')
def ready():
    database_ok = database_ping(app.config)
    storage_configured = (
        app.config['STORAGE_BACKEND'] == 'local'
        or not required_r2_values(app.config)
    )
    status = 200 if database_ok and storage_configured else 503
    return {
        'status': 'ready' if status == 200 else 'not_ready',
        'database': 'ok' if database_ok else 'unavailable',
        'storage': 'configured' if storage_configured else 'misconfigured',
    }, status


@app.after_request
def disable_private_response_caching(response):
    private_prefixes = (
        '/connexion', '/inscription', '/auth/', '/dashboard', '/eleve',
        '/professeur', '/devoir/', '/uploads/', '/mon-compte', '/rendre_copie',
    )
    if current_user.is_authenticated or request.path.startswith(private_prefixes):
        response.headers['Cache-Control'] = 'no-store, private'
        response.headers['Pragma'] = 'no-cache'
    return response


if __name__ == '__main__':
    app.run(debug=True)
