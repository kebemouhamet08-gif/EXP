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
    Index,
    func,
    text as sql_text,
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
    CheckConstraint("role IN ('ELEVE', 'PROFESSEUR', 'ADMIN')", name="role_valide"),
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
    Column("role", String(20), nullable=False, server_default="ELEVE"),
    Column("statut", String(20), nullable=False, server_default="ACTIVE"),
    Column("removed_at", DateTime),
    Column("removed_by", Integer, ForeignKey("utilisateurs.id")),
    Column("can_view_members", Boolean, nullable=False, server_default="true"),
    Column("can_send_announcements", Boolean, nullable=False, server_default="false"),
    Column("can_contact_students", Boolean, nullable=False, server_default="false"),
    Column("can_contact_teachers", Boolean, nullable=False, server_default="true"),
    CheckConstraint("role IN ('ELEVE', 'RESPONSABLE')", name="role_classe_valide"),
    CheckConstraint("statut IN ('ACTIVE', 'REMOVED')", name="statut_membre_valide"),
)

classe_professeurs = Table(
    "classe_professeurs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("classe_id", Integer, ForeignKey("classes.id", ondelete="CASCADE"), nullable=False),
    Column("professeur_id", Integer, ForeignKey("utilisateurs.id", ondelete="CASCADE"), nullable=False),
    Column("role", String(20), nullable=False),
    Column("ajoute_par", Integer, ForeignKey("utilisateurs.id")),
    Column("date_ajout", DateTime, nullable=False, server_default=func.now()),
    CheckConstraint("role IN ('OWNER', 'PROFESSEUR')", name="role_classe_prof_valide"),
    UniqueConstraint("classe_id", "professeur_id", name="uq_classe_professeur"),
    Index("ix_classe_professeurs_classe_role", "classe_id", "role"),
)
Index("uq_classe_single_owner", classe_professeurs.c.classe_id, unique=True,
      sqlite_where=sql_text("role = 'OWNER'"), postgresql_where=sql_text("role = 'OWNER'"))

class_settings = Table(
    "class_settings", metadata,
    Column("classe_id", Integer, ForeignKey("classes.id", ondelete="CASCADE"), primary_key=True),
    Column("chat_enabled", Boolean, nullable=False, server_default="false"),
    Column("students_can_start", Boolean, nullable=False, server_default="false"),
    Column("responsables_can_contact_students", Boolean, nullable=False, server_default="false"),
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
    Column("correction_text", Text),
    Column("correction_visibility", String(30), nullable=False, server_default="NEVER"),
    Column("correction_visible_at", DateTime),
    CheckConstraint(
        "correction_visibility IN ('NEVER', 'AFTER_END', 'AFTER_SUBMISSION', 'AT_DATE', 'NOW')",
        name="correction_visibility_valide",
    ),
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
    CheckConstraint("kind IN ('SUJET', 'COPIE', 'CORRECTION', 'PHOTO', 'SITE_IMAGE')", name="kind_valide"),
    UniqueConstraint("session_id", "photo_index", name="uq_fichier_session_photo_index"),
)

conversations = Table(
    "conversations", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("classe_id", Integer, ForeignKey("classes.id", ondelete="CASCADE"), nullable=False),
    Column("type", String(30), nullable=False, server_default="TEACHER_STUDENT"),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("created_by", Integer, ForeignKey("utilisateurs.id"), nullable=False),
)
conversation_participants = Table(
    "conversation_participants", metadata,
    Column("conversation_id", Integer, ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True),
    Column("utilisateur_id", Integer, ForeignKey("utilisateurs.id", ondelete="CASCADE"), primary_key=True),
    Column("joined_at", DateTime, nullable=False, server_default=func.now()),
)
messages = Table(
    "messages", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("conversation_id", Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
    Column("auteur_id", Integer, ForeignKey("utilisateurs.id"), nullable=False),
    Column("contenu", Text, nullable=False),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("lu_at", DateTime), Column("edited_at", DateTime),
    Index("ix_messages_conversation_created", "conversation_id", "created_at"),
)
notifications = Table(
    "notifications", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("utilisateur_id", Integer, ForeignKey("utilisateurs.id", ondelete="CASCADE"), nullable=False),
    Column("type", String(50), nullable=False), Column("titre", Text, nullable=False),
    Column("message", Text, nullable=False), Column("url", Text), Column("lu_at", DateTime),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Index("ix_notifications_user_read", "utilisateur_id", "lu_at"),
)
site_content = Table(
    "site_content", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("key", String(100), nullable=False, unique=True), Column("title", Text),
    Column("content", Text), Column("image_object_key", Text), Column("link_url", Text),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("position", Integer, nullable=False, server_default="0"),
    Column("updated_by", Integer, ForeignKey("utilisateurs.id")),
    Column("updated_at", DateTime, nullable=False, server_default=func.now()),
)
site_banners = Table(
    "site_banners", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("enabled", Boolean, nullable=False, server_default="false"),
    Column("type", String(20), nullable=False, server_default="INFO"),
    Column("message", Text, nullable=False), Column("link", Text),
    Column("starts_at", DateTime), Column("ends_at", DateTime),
    Column("updated_by", Integer, ForeignKey("utilisateurs.id")),
    CheckConstraint("type IN ('INFO', 'SUCCESS', 'WARNING', 'IMPORTANT')", name="banner_type_valide"),
)
site_settings = Table(
    "site_settings", metadata,
    Column("id", Integer, primary_key=True), Column("public_name", Text, nullable=False, server_default="ClasseXP"),
    Column("description", Text), Column("logo_object_key", Text), Column("favicon_object_key", Text),
    Column("home_image_object_key", Text), Column("primary_color", String(20), nullable=False, server_default="indigo"),
    Column("maintenance_enabled", Boolean, nullable=False, server_default="false"),
    Column("maintenance_message", Text), Column("maintenance_starts_at", DateTime), Column("maintenance_ends_at", DateTime),
    Column("updated_by", Integer, ForeignKey("utilisateurs.id")), Column("updated_at", DateTime, nullable=False, server_default=func.now()),
)
audit_logs = Table(
    "audit_logs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("actor_user_id", Integer, ForeignKey("utilisateurs.id")), Column("action", String(100), nullable=False),
    Column("entity_type", String(50), nullable=False), Column("entity_id", String(100)),
    Column("metadata_json", Text), Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Index("ix_audit_logs_created_at", "created_at"),
)

