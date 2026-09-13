"""SQLAlchemy Core schema shared by Flask, Alembic and migration tools."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = MetaData(naming_convention=NAMING_CONVENTION)

utilisateurs = Table(
    "utilisateurs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("nom", Text, nullable=False),
    Column("email", String(320), nullable=False, unique=True),
    Column("mot_de_passe_hash", Text),
    Column("role", String(20), nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    CheckConstraint("role IN ('ELEVE', 'PROFESSEUR')", name="role_valide"),
)

identites_externes = Table(
    "identites_externes",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("utilisateur_id", Integer, ForeignKey("utilisateurs.id", ondelete="CASCADE"), nullable=False),
    Column("provider", String(20), nullable=False),
    Column("provider_subject", Text, nullable=False),
    Column("email_provider", String(320)),
    Column("email_verified", Boolean, nullable=False, server_default="false"),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("last_login_at", DateTime, nullable=False, server_default=func.now()),
    CheckConstraint(
        "provider IN ('google', 'facebook', 'apple', 'microsoft')",
        name="provider_valide",
    ),
    UniqueConstraint("provider", "provider_subject", name="uq_identite_provider_subject"),
)

classes = Table(
    "classes",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("nom", Text, nullable=False),
    Column("professeur_id", Integer, ForeignKey("utilisateurs.id")),
    Column("code", String(32), nullable=False, unique=True),
)

classe_eleves = Table(
    "classe_eleves",
    metadata,
    Column("classe_id", Integer, ForeignKey("classes.id", ondelete="CASCADE"), primary_key=True),
    Column("eleve_id", Integer, ForeignKey("utilisateurs.id", ondelete="CASCADE"), primary_key=True),
)

devoirs = Table(
    "devoirs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("titre", Text, nullable=False),
    Column("description", Text),
    Column("professeur_id", Integer, ForeignKey("utilisateurs.id")),
    Column("classe_id", Integer, ForeignKey("classes.id")),
    Column("sujet_pdf", Text),
    Column("date_ouverture", DateTime),
    Column("duree", Integer, nullable=False),
    Column("correction_pdf", Text),
)

sessions_examen = Table(
    "sessions_examen",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("eleve_id", Integer, ForeignKey("utilisateurs.id")),
    Column("devoir_id", Integer, ForeignKey("devoirs.id")),
    Column("heure_debut", DateTime, nullable=False),
    Column("heure_fin", DateTime),
    Column("statut", String(20), server_default="EN_COURS"),
    Column("fichier_copie", Text),
    Column("note", Float),
    Column("commentaire", Text),
    CheckConstraint("statut IN ('EN_COURS', 'TERMINE')", name="statut_valide"),
    UniqueConstraint("eleve_id", "devoir_id", name="uq_session_eleve_devoir"),
)

fichiers = Table(
    "fichiers",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("storage_key", Text, nullable=False, unique=True),
    Column("original_filename", Text, nullable=False),
    Column("content_type", String(255), nullable=False),
    Column("size", Integer, nullable=False),
    Column("kind", String(20), nullable=False),
    Column("owner_user_id", Integer, ForeignKey("utilisateurs.id")),
    Column("devoir_id", Integer, ForeignKey("devoirs.id", ondelete="CASCADE")),
    Column("session_id", Integer, ForeignKey("sessions_examen.id", ondelete="CASCADE")),
    Column("photo_index", Integer),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    CheckConstraint("kind IN ('SUJET', 'COPIE', 'CORRECTION', 'PHOTO')", name="kind_valide"),
    UniqueConstraint("session_id", "photo_index", name="uq_fichier_session_photo_index"),
)

