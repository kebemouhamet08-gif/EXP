-- Schema SQLite historique utilisé pour les migrations de données existantes.
-- Les tables avancées du projet (multi-professeurs, CMS, chat, etc.) sont
-- gérées par le modèle SQLAlchemy et les migrations Alembic, pas par ce fichier.
DROP TABLE IF EXISTS fichiers;
DROP TABLE IF EXISTS sessions_examen;
DROP TABLE IF EXISTS devoirs;
DROP TABLE IF EXISTS classe_eleves;
DROP TABLE IF EXISTS classes;
DROP TABLE IF EXISTS identites_externes;
DROP TABLE IF EXISTS utilisateurs;

CREATE TABLE utilisateurs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    mot_de_passe_hash TEXT,
    role TEXT CHECK(role IN ('ELEVE', 'PROFESSEUR', 'ADMIN')) NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE identites_externes (
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
);

CREATE TABLE classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL,
    professeur_id INTEGER,
    code TEXT UNIQUE NOT NULL,
    FOREIGN KEY (professeur_id) REFERENCES utilisateurs(id)
);

CREATE TABLE classe_eleves (
    classe_id INTEGER NOT NULL,
    eleve_id INTEGER NOT NULL,
    PRIMARY KEY (classe_id, eleve_id),
    FOREIGN KEY (classe_id) REFERENCES classes(id) ON DELETE CASCADE,
    FOREIGN KEY (eleve_id) REFERENCES utilisateurs(id) ON DELETE CASCADE
);

CREATE TABLE devoirs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titre TEXT NOT NULL,
    description TEXT,
    professeur_id INTEGER,
    classe_id INTEGER,
    sujet_pdf TEXT,
    date_ouverture DATETIME,
    duree INTEGER NOT NULL,
    correction_pdf TEXT,
    FOREIGN KEY (professeur_id) REFERENCES utilisateurs(id),
    FOREIGN KEY (classe_id) REFERENCES classes(id)
);

CREATE TABLE sessions_examen (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eleve_id INTEGER,
    devoir_id INTEGER,
    heure_debut DATETIME NOT NULL,
    heure_fin DATETIME,
    statut TEXT CHECK(statut IN ('EN_COURS', 'TERMINE')) DEFAULT 'EN_COURS',
    fichier_copie TEXT,
    note REAL,
    commentaire TEXT,
    FOREIGN KEY (eleve_id) REFERENCES utilisateurs(id),
    FOREIGN KEY (devoir_id) REFERENCES devoirs(id),
    UNIQUE (eleve_id, devoir_id)
);

CREATE TABLE fichiers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    storage_key TEXT UNIQUE NOT NULL,
    original_filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size INTEGER NOT NULL,
    kind TEXT CHECK(kind IN ('SUJET', 'COPIE', 'CORRECTION', 'PHOTO', 'SITE_IMAGE')) NOT NULL,
    owner_user_id INTEGER,
    devoir_id INTEGER,
    session_id INTEGER,
    photo_index INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_user_id) REFERENCES utilisateurs(id),
    FOREIGN KEY (devoir_id) REFERENCES devoirs(id) ON DELETE CASCADE,
    FOREIGN KEY (session_id) REFERENCES sessions_examen(id) ON DELETE CASCADE,
    UNIQUE (session_id, photo_index)
);
