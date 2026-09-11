-- Reinitialise les tables lors de la commande flask init-db.
DROP TABLE IF EXISTS sessions_examen;
DROP TABLE IF EXISTS devoirs;
DROP TABLE IF EXISTS classes;
DROP TABLE IF EXISTS utilisateurs;

CREATE TABLE utilisateurs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    mot_de_passe_hash TEXT NOT NULL,
    role TEXT CHECK(role IN ('ELEVE', 'PROFESSEUR', 'ADMIN')) NOT NULL
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