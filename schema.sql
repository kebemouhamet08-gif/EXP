PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS utilisateurs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    mot_de_passe_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('STUDENT', 'TEACHER')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    account_status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (account_status IN ('ACTIVE', 'DISABLED'))
);

CREATE TABLE IF NOT EXISTS classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL,
    professeur_id INTEGER NOT NULL,
    FOREIGN KEY (professeur_id) REFERENCES utilisateurs(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS devoirs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titre TEXT NOT NULL,
    description TEXT,
    professeur_id INTEGER NOT NULL,
    classe_id INTEGER NOT NULL,
    sujet_pdf TEXT,
    date_ouverture TEXT,
    duree INTEGER NOT NULL CHECK (duree > 0),
    correction_pdf TEXT,
    FOREIGN KEY (professeur_id) REFERENCES utilisateurs(id) ON DELETE RESTRICT,
    FOREIGN KEY (classe_id) REFERENCES classes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sessions_examen (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eleve_id INTEGER NOT NULL,
    devoir_id INTEGER NOT NULL,
    heure_debut TEXT NOT NULL,
    heure_fin TEXT,
    statut TEXT NOT NULL DEFAULT 'EN_COURS' CHECK (statut IN ('EN_COURS', 'TERMINE')),
    fichier_copie TEXT,
    UNIQUE (eleve_id, devoir_id),
    FOREIGN KEY (eleve_id) REFERENCES utilisateurs(id) ON DELETE CASCADE,
    FOREIGN KEY (devoir_id) REFERENCES devoirs(id) ON DELETE CASCADE
);
